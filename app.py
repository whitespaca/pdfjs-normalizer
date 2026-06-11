import concurrent.futures as futures
import io
import os
import queue
import re
import threading
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import fitz  # PyMuPDF
from PIL import Image


APP_TITLE = "PDF.js 호환 PDF 일괄 변환기"
APP_VERSION = "1.2.0"

# Removes marked-content blocks like:
# /Artifact <</Subtype /Watermark /Type /Pagination >>BDC ... EMC
# This intentionally targets explicit PDF watermark artifacts only.
WATERMARK_ARTIFACT_RE = re.compile(
    rb"/Artifact\s*<<(?:(?!>>).)*(?:/Subtype\s*/Watermark|/Type\s*/Pagination)(?:(?!>>).)*>>\s*BDC\s*.*?\s*EMC\s*",
    re.DOTALL,
)


@dataclass(frozen=True)
class ConvertOptions:
    input_dir: Path
    output_dir: Path
    dpi: int
    image_format: str
    jpeg_quality: int
    workers: int
    skip_existing: bool
    suffix: str
    remove_watermark_artifacts: bool
    raster_watermark_cleanup: bool
    bw_threshold: int


@dataclass(frozen=True)
class ConvertResult:
    status: str
    source: str
    output: str
    message: str = ""
    elapsed_sec: float = 0.0
    watermark_blocks_removed: int = 0
    raster_pages_cleaned: int = 0


def iter_pdfs(input_dir: Path) -> list[Path]:
    return sorted(
        p for p in input_dir.rglob("*.pdf")
        if p.is_file() and not p.name.startswith("~$")
    )


def output_path_for(src: Path, options: ConvertOptions) -> Path:
    rel = src.relative_to(options.input_dir)
    if options.suffix.strip():
        rel = rel.with_name(f"{rel.stem}{options.suffix}{rel.suffix}")
    return options.output_dir / rel


def strip_watermark_artifacts(doc: fitz.Document) -> int:
    """Remove explicit /Artifact Watermark marked-content blocks from page streams.

    This does not edit the source file on disk. The opened document is modified in
    memory before rasterization. It is deliberately conservative and only removes
    content blocks marked as /Subtype /Watermark or /Type /Pagination.
    """
    total_removed = 0
    updated_streams: set[int] = set()

    for page in doc:
        for content_xref in page.get_contents():
            if content_xref in updated_streams:
                continue

            try:
                data = doc.xref_stream(content_xref)
            except Exception:
                continue

            if not data:
                continue

            new_data, removed = WATERMARK_ARTIFACT_RE.subn(b"", data)
            if removed:
                doc.update_stream(content_xref, new_data)
                updated_streams.add(content_xref)
                total_removed += removed

    return total_removed


def pixmap_to_image_bytes(
    pix: fitz.Pixmap,
    image_format: str,
    jpeg_quality: int,
    raster_watermark_cleanup: bool,
    bw_threshold: int,
) -> tuple[bytes, bool]:
    """Return page image bytes.

    When raster_watermark_cleanup is enabled, the rendered page is converted to
    black/white by thresholding. This removes light gray and colored watermarks
    that have already been baked into the page bitmap. It is suitable for black
    music-score pages on a white background; it can remove intentional light-gray
    content.
    """
    if not raster_watermark_cleanup:
        if image_format == "jpeg":
            return pix.tobytes("jpeg", jpg_quality=jpeg_quality), False
        return pix.tobytes("png"), False

    mode = "RGBA" if pix.alpha else "RGB"
    img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    if mode == "RGBA":
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        white.alpha_composite(img)
        img = white.convert("RGB")

    gray = img.convert("L")
    # Pixels darker than the threshold become black; everything else becomes white.
    # Default 180 works well for MusicScore-like colored/gray overlay watermarks.
    bw = gray.point(lambda value: 0 if value < bw_threshold else 255, mode="1")

    buffer = io.BytesIO()
    if image_format == "jpeg":
        bw.convert("L").save(buffer, format="JPEG", quality=jpeg_quality, optimize=True)
    else:
        bw.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), True


def convert_pdf(src: Path, options: ConvertOptions, cancel_event: threading.Event) -> ConvertResult:
    started = time.perf_counter()
    dst = output_path_for(src, options)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    watermark_blocks_removed = 0
    raster_pages_cleaned = 0

    if options.skip_existing and dst.exists() and dst.stat().st_size > 0:
        return ConvertResult("skip", str(src), str(dst), "already exists", time.perf_counter() - started)

    try:
        if cancel_event.is_set():
            return ConvertResult("cancel", str(src), str(dst), "cancel requested", time.perf_counter() - started)

        dst.parent.mkdir(parents=True, exist_ok=True)

        src_doc = fitz.open(src)
        if src_doc.needs_pass:
            src_doc.close()
            return ConvertResult("fail", str(src), str(dst), "encrypted/password protected", time.perf_counter() - started)

        if options.remove_watermark_artifacts:
            watermark_blocks_removed = strip_watermark_artifacts(src_doc)

        out_doc = fitz.open()
        matrix = fitz.Matrix(options.dpi / 72.0, options.dpi / 72.0)

        for page_index in range(src_doc.page_count):
            if cancel_event.is_set():
                out_doc.close()
                src_doc.close()
                if tmp.exists():
                    tmp.unlink(missing_ok=True)
                return ConvertResult(
                    "cancel",
                    str(src),
                    str(dst),
                    "cancel requested",
                    time.perf_counter() - started,
                    watermark_blocks_removed,
                    raster_pages_cleaned,
                )

            page = src_doc.load_page(page_index)
            page_rect = page.rect
            pix = page.get_pixmap(matrix=matrix, alpha=False, annots=True)
            image_bytes, cleaned = pixmap_to_image_bytes(
                pix,
                options.image_format,
                options.jpeg_quality,
                options.raster_watermark_cleanup,
                options.bw_threshold,
            )
            if cleaned:
                raster_pages_cleaned += 1

            new_page = out_doc.new_page(width=page_rect.width, height=page_rect.height)
            new_page.insert_image(page_rect, stream=image_bytes)

        out_doc.save(
            tmp,
            garbage=4,
            deflate=True,
            clean=True,
        )
        out_doc.close()
        src_doc.close()

        os.replace(tmp, dst)
        message = "converted"
        if options.remove_watermark_artifacts:
            message += f"; watermark artifact blocks removed={watermark_blocks_removed}"
        if options.raster_watermark_cleanup:
            message += f"; raster pages cleaned={raster_pages_cleaned}; bw_threshold={options.bw_threshold}"
        return ConvertResult(
            "ok",
            str(src),
            str(dst),
            message,
            time.perf_counter() - started,
            watermark_blocks_removed,
            raster_pages_cleaned,
        )

    except Exception:
        try:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return ConvertResult(
            "fail",
            str(src),
            str(dst),
            traceback.format_exc(),
            time.perf_counter() - started,
            watermark_blocks_removed,
            raster_pages_cleaned,
        )


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("1040x760")
        self.minsize(920, 650)

        self.event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker_thread: threading.Thread | None = None
        self.total_count = 0
        self.done_count = 0
        self.counts = {"ok": 0, "skip": 0, "fail": 0, "cancel": 0}
        self.watermark_blocks_total = 0
        self.raster_pages_cleaned_total = 0

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.dpi_var = tk.IntVar(value=200)
        self.format_var = tk.StringVar(value="png")
        self.quality_var = tk.IntVar(value=95)
        self.workers_var = tk.IntVar(value=min(6, max(1, os.cpu_count() or 1)))
        self.skip_var = tk.BooleanVar(value=True)
        self.suffix_var = tk.StringVar(value="-pdfjs")
        self.remove_watermark_var = tk.BooleanVar(value=False)
        self.raster_cleanup_var = tk.BooleanVar(value=False)
        self.bw_threshold_var = tk.IntVar(value=180)
        self.status_var = tk.StringVar(value="대기 중")

        self._build_ui()
        self.after(120, self._poll_queue)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill=tk.BOTH, expand=True)

        top = ttk.LabelFrame(outer, text="입출력", padding=12)
        top.pack(fill=tk.X)

        ttk.Label(top, text="원본 PDF 폴더").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=5)
        ttk.Entry(top, textvariable=self.input_var).grid(row=0, column=1, sticky=tk.EW, pady=5)
        ttk.Button(top, text="선택", command=self.choose_input).grid(row=0, column=2, padx=(8, 0), pady=5)

        ttk.Label(top, text="변환본 저장 폴더").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=5)
        ttk.Entry(top, textvariable=self.output_var).grid(row=1, column=1, sticky=tk.EW, pady=5)
        ttk.Button(top, text="선택", command=self.choose_output).grid(row=1, column=2, padx=(8, 0), pady=5)
        top.columnconfigure(1, weight=1)

        options = ttk.LabelFrame(outer, text="변환 옵션", padding=12)
        options.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(options, text="DPI").grid(row=0, column=0, sticky=tk.W, padx=(0, 8), pady=5)
        ttk.Spinbox(options, from_=120, to=400, increment=10, textvariable=self.dpi_var, width=8).grid(row=0, column=1, sticky=tk.W, pady=5)

        ttk.Label(options, text="이미지 형식").grid(row=0, column=2, sticky=tk.W, padx=(24, 8), pady=5)
        fmt = ttk.Combobox(options, values=["png", "jpeg"], textvariable=self.format_var, state="readonly", width=8)
        fmt.grid(row=0, column=3, sticky=tk.W, pady=5)
        fmt.bind("<<ComboboxSelected>>", lambda _e: self._sync_quality_state())

        ttk.Label(options, text="JPEG 품질").grid(row=0, column=4, sticky=tk.W, padx=(24, 8), pady=5)
        self.quality_spin = ttk.Spinbox(options, from_=50, to=100, increment=1, textvariable=self.quality_var, width=8)
        self.quality_spin.grid(row=0, column=5, sticky=tk.W, pady=5)

        ttk.Label(options, text="동시 작업 수").grid(row=1, column=0, sticky=tk.W, padx=(0, 8), pady=5)
        ttk.Spinbox(options, from_=1, to=max(1, (os.cpu_count() or 4) * 2), increment=1, textvariable=self.workers_var, width=8).grid(row=1, column=1, sticky=tk.W, pady=5)

        ttk.Label(options, text="파일명 접미사").grid(row=1, column=2, sticky=tk.W, padx=(24, 8), pady=5)
        ttk.Entry(options, textvariable=self.suffix_var, width=16).grid(row=1, column=3, sticky=tk.W, pady=5)

        ttk.Checkbutton(options, text="이미 존재하는 변환본은 건너뛰기", variable=self.skip_var).grid(row=1, column=4, columnspan=2, sticky=tk.W, padx=(24, 0), pady=5)

        watermark_box = ttk.LabelFrame(outer, text="권한 있는 문서 전용 옵션", padding=12)
        watermark_box.pack(fill=tk.X, pady=(12, 0))
        ttk.Checkbutton(
            watermark_box,
            text="명시적 PDF 워터마크 Artifact 제거 후 변환",
            variable=self.remove_watermark_var,
        ).grid(row=0, column=0, sticky=tk.W, pady=2)

        ttk.Label(
            watermark_box,
            text="/Artifact + /Subtype /Watermark 또는 /Type /Pagination으로 표시된 별도 워터마크 블록만 제거합니다.",
        ).grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(2, 8))

        ttk.Checkbutton(
            watermark_box,
            text="이미지에 합쳐진 연한/컬러 워터마크 제거 시도: 흑백 임계값 변환",
            variable=self.raster_cleanup_var,
        ).grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=2)

        ttk.Label(watermark_box, text="임계값").grid(row=2, column=2, sticky=tk.W, padx=(24, 8))
        ttk.Spinbox(watermark_box, from_=80, to=240, increment=5, textvariable=self.bw_threshold_var, width=8).grid(row=2, column=3, sticky=tk.W)

        ttk.Label(
            watermark_box,
            text="이미 워터마크가 본문 이미지와 합쳐진 PDF용입니다. 검은 악보/흰 배경 문서에 적합하며, 연한 회색 요소는 사라질 수 있습니다. 기본값 180 권장.",
        ).grid(row=3, column=0, columnspan=4, sticky=tk.W, pady=(2, 0))

        self._sync_quality_state()

        actions = ttk.Frame(outer)
        actions.pack(fill=tk.X, pady=(12, 0))

        self.start_button = ttk.Button(actions, text="변환 시작", command=self.start)
        self.start_button.pack(side=tk.LEFT)
        self.cancel_button = ttk.Button(actions, text="취소", command=self.cancel, state=tk.DISABLED)
        self.cancel_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(actions, textvariable=self.status_var).pack(side=tk.LEFT, padx=(18, 0))

        self.progress = ttk.Progressbar(outer, orient=tk.HORIZONTAL, mode="determinate")
        self.progress.pack(fill=tk.X, pady=(12, 0))

        log_frame = ttk.LabelFrame(outer, text="로그", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.log_text = tk.Text(log_frame, wrap=tk.NONE, height=18)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        yscroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=yscroll.set)

        self._log("PDF.js에서 불안정한 PDF를 페이지 이미지 기반 PDF로 정규화합니다.")
        self._log("권장 시작값: DPI 200, PNG, workers 6. 파일 크기가 크면 JPEG 95를 테스트하세요.")
        self._log("워터마크 제거 옵션은 권한이 있는 PDF에서만 사용하세요.")
        self._log("이미지에 합쳐진 워터마크는 '흑백 임계값 변환' 옵션을 사용하세요. 기본 임계값 180.")

    def _sync_quality_state(self) -> None:
        if self.format_var.get() == "jpeg":
            self.quality_spin.configure(state="normal")
        else:
            self.quality_spin.configure(state="disabled")

    def choose_input(self) -> None:
        path = filedialog.askdirectory(title="원본 PDF 폴더 선택")
        if path:
            self.input_var.set(path)
            if not self.output_var.get():
                self.output_var.set(str(Path(path).with_name(Path(path).name + "-pdfjs-compatible")))

    def choose_output(self) -> None:
        path = filedialog.askdirectory(title="변환본 저장 폴더 선택")
        if path:
            self.output_var.set(path)

    def _validate_options(self) -> ConvertOptions | None:
        input_dir = Path(self.input_var.get()).expanduser().resolve()
        output_dir = Path(self.output_var.get()).expanduser().resolve()

        if not input_dir.exists() or not input_dir.is_dir():
            messagebox.showerror("입력 오류", "원본 PDF 폴더를 올바르게 선택하세요.")
            return None
        if input_dir == output_dir:
            messagebox.showerror("입력 오류", "원본 폴더와 출력 폴더는 달라야 합니다.")
            return None

        try:
            dpi = int(self.dpi_var.get())
            jpeg_quality = int(self.quality_var.get())
            workers = int(self.workers_var.get())
            bw_threshold = int(self.bw_threshold_var.get())
        except Exception:
            messagebox.showerror("입력 오류", "DPI, JPEG 품질, 동시 작업 수, 임계값은 숫자여야 합니다.")
            return None

        if dpi < 120 or dpi > 400:
            messagebox.showerror("입력 오류", "DPI는 120~400 범위로 지정하세요.")
            return None
        if jpeg_quality < 50 or jpeg_quality > 100:
            messagebox.showerror("입력 오류", "JPEG 품질은 50~100 범위로 지정하세요.")
            return None
        if workers < 1:
            messagebox.showerror("입력 오류", "동시 작업 수는 1 이상이어야 합니다.")
            return None
        if bw_threshold < 80 or bw_threshold > 240:
            messagebox.showerror("입력 오류", "흑백 임계값은 80~240 범위로 지정하세요.")
            return None

        return ConvertOptions(
            input_dir=input_dir,
            output_dir=output_dir,
            dpi=dpi,
            image_format=self.format_var.get(),
            jpeg_quality=jpeg_quality,
            workers=workers,
            skip_existing=bool(self.skip_var.get()),
            suffix=self.suffix_var.get(),
            remove_watermark_artifacts=bool(self.remove_watermark_var.get()),
            raster_watermark_cleanup=bool(self.raster_cleanup_var.get()),
            bw_threshold=bw_threshold,
        )

    def start(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        options = self._validate_options()
        if options is None:
            return

        pdfs = iter_pdfs(options.input_dir)
        if not pdfs:
            messagebox.showinfo("PDF 없음", "선택한 폴더에 PDF 파일이 없습니다.")
            return

        if options.remove_watermark_artifacts or options.raster_watermark_cleanup:
            ok = messagebox.askyesno(
                "권한 확인",
                "워터마크 제거 관련 옵션이 켜져 있습니다.\n\n이 옵션은 권한이 있는 PDF에서만 사용해야 합니다. 계속할까요?",
            )
            if not ok:
                return

        self.cancel_event.clear()
        self.total_count = len(pdfs)
        self.done_count = 0
        self.counts = {"ok": 0, "skip": 0, "fail": 0, "cancel": 0}
        self.watermark_blocks_total = 0
        self.raster_pages_cleaned_total = 0
        self.progress.configure(maximum=self.total_count, value=0)
        self.start_button.configure(state=tk.DISABLED)
        self.cancel_button.configure(state=tk.NORMAL)
        self.status_var.set(f"0 / {self.total_count} 처리 중")
        self._log("-" * 90)
        self._log(f"대상 PDF: {self.total_count}개")
        self._log(f"입력: {options.input_dir}")
        self._log(f"출력: {options.output_dir}")
        self._log(
            f"옵션: DPI={options.dpi}, format={options.image_format}, quality={options.jpeg_quality}, "
            f"workers={options.workers}, remove_watermark_artifacts={options.remove_watermark_artifacts}, "
            f"raster_watermark_cleanup={options.raster_watermark_cleanup}, bw_threshold={options.bw_threshold}"
        )

        self.worker_thread = threading.Thread(
            target=self._worker_main,
            args=(pdfs, options),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state=tk.DISABLED)
        self.status_var.set("취소 요청됨: 진행 중인 파일 완료 후 중단")
        self._log("취소 요청됨")

    def _worker_main(self, pdfs: list[Path], options: ConvertOptions) -> None:
        options.output_dir.mkdir(parents=True, exist_ok=True)
        log_path = options.output_dir / "_conversion-log.tsv"

        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write("status\tsource\toutput\telapsed_sec\twatermark_blocks_removed\traster_pages_cleaned\tmessage\n")
            log_file.flush()

            try:
                with futures.ThreadPoolExecutor(max_workers=options.workers) as executor:
                    future_map = {}
                    for src in pdfs:
                        if self.cancel_event.is_set():
                            break
                        fut = executor.submit(convert_pdf, src, options, self.cancel_event)
                        future_map[fut] = src

                    for fut in futures.as_completed(future_map):
                        result = fut.result()
                        safe_msg = result.message.replace("\r", " ").replace("\n", " | ")
                        log_file.write(
                            f"{result.status}\t{result.source}\t{result.output}\t{result.elapsed_sec:.2f}\t"
                            f"{result.watermark_blocks_removed}\t{result.raster_pages_cleaned}\t{safe_msg}\n"
                        )
                        log_file.flush()
                        self.event_queue.put(("result", result))

                        if self.cancel_event.is_set():
                            pass
            except Exception:
                self.event_queue.put(("fatal", traceback.format_exc()))
            finally:
                self.event_queue.put(("done", str(log_path)))

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self.event_queue.get_nowait()
                if event == "result":
                    self._handle_result(payload)  # type: ignore[arg-type]
                elif event == "fatal":
                    self._log("치명적 오류:\n" + str(payload))
                elif event == "done":
                    self._finish(str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _handle_result(self, result: ConvertResult) -> None:
        self.done_count += 1
        self.counts[result.status] = self.counts.get(result.status, 0) + 1
        self.watermark_blocks_total += result.watermark_blocks_removed
        self.raster_pages_cleaned_total += result.raster_pages_cleaned
        self.progress.configure(value=self.done_count)

        name = Path(result.source).name
        extra_info = ""
        if result.watermark_blocks_removed:
            extra_info += f" | watermark blocks removed={result.watermark_blocks_removed}"
        if result.raster_pages_cleaned:
            extra_info += f" | raster pages cleaned={result.raster_pages_cleaned}"

        if result.status == "ok":
            self._log(f"[OK] {name} -> {result.output} ({result.elapsed_sec:.1f}s){extra_info}")
        elif result.status == "skip":
            self._log(f"[SKIP] {name}")
        elif result.status == "cancel":
            self._log(f"[CANCEL] {name}{extra_info}")
        else:
            self._log(f"[FAIL] {name}{extra_info}\n{result.message}")

        self.status_var.set(
            f"{self.done_count} / {self.total_count} | "
            f"성공 {self.counts.get('ok', 0)}, 건너뜀 {self.counts.get('skip', 0)}, 실패 {self.counts.get('fail', 0)}, "
            f"Artifact 제거 {self.watermark_blocks_total}, 이미지 정리 {self.raster_pages_cleaned_total}p"
        )

    def _finish(self, log_path: str) -> None:
        self.start_button.configure(state=tk.NORMAL)
        self.cancel_button.configure(state=tk.DISABLED)
        self.status_var.set(
            f"완료 | 성공 {self.counts.get('ok', 0)}, 건너뜀 {self.counts.get('skip', 0)}, "
            f"실패 {self.counts.get('fail', 0)}, 취소 {self.counts.get('cancel', 0)}, "
            f"Artifact 제거 {self.watermark_blocks_total}, 이미지 정리 {self.raster_pages_cleaned_total}p"
        )
        self._log(f"로그 파일: {log_path}")
        self._log("완료")

    def _log(self, text: str) -> None:
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
