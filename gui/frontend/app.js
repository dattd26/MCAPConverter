/**
 * MCAP STUDIO - Frontend Application Logic
 * Quản lý quy trình 4 bước, WebSocket logs, native file dialogs, Foxglove Studio, và Splitter.
 */

// Trạng thái toàn cục của ứng dụng
const AppState = {
  currentStep: 1,
  activeSessionDir: "",
  step1OutputDir: "",
  step2RepackedDir: "",
  step3SplitDir: "",
  isTaskRunning: false,
  step3ScanData: null,
  step4ScanData: null,
};

document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initPillSelectors();
  initSystemAPIs();
  initWebSocket();
  initStep1();
  initStep2();
  initStep3();
  initStep4();
  initTerminal();
});

// ==========================================
// 1. NAVIGATION & STEPPER
// ==========================================
function initNavigation() {
  const stepItems = document.querySelectorAll(".step-item");
  stepItems.forEach(item => {
    item.addEventListener("click", () => {
      const step = parseInt(item.getAttribute("data-step"), 10);
      switchTab(step);
    });
  });

  // Nút chuyển tiếp giữa các bước
  document.getElementById("btn-next-to-step2").addEventListener("click", () => {
    // Chuyển tiếp thư mục từ Bước 1 sang Bước 2
    const s1Src = document.getElementById("step1-src-dir").value.trim();
    if (s1Src && !document.getElementById("step2-orig-dir").value) {
      document.getElementById("step2-orig-dir").value = s1Src;
    }
    switchTab(2);
  });

  document.getElementById("btn-next-to-step3").addEventListener("click", () => {
    // Chuyển tiếp thư mục repacked từ Bước 2 sang Bước 3
    const s2Out = document.getElementById("step2-out-dir").value.trim();
    const s2Orig = document.getElementById("step2-orig-dir").value.trim();
    const target = s2Out || (s2Orig ? `${s2Orig}_repacked` : "");
    if (target && !document.getElementById("step3-target-dir").value) {
      document.getElementById("step3-target-dir").value = target;
      scanStep3Parts(target);
    }
    switchTab(3);
  });

  document.getElementById("btn-next-to-step4").addEventListener("click", () => {
    // Chuyển tiếp thư mục vừa tách sang Bước 4
    const s3Target = document.getElementById("step3-target-dir").value.trim();
    if (s3Target && !document.getElementById("step4-parent-dir").value) {
      document.getElementById("step4-parent-dir").value = s3Target;
      scanStep4Targets(s3Target);
    }
    switchTab(4);
  });
}

function switchTab(stepNumber) {
  AppState.currentStep = stepNumber;

  // Cập nhật Stepper
  document.querySelectorAll(".step-item").forEach(item => {
    const s = parseInt(item.getAttribute("data-step"), 10);
    item.classList.remove("active");
    if (s === stepNumber) {
      item.classList.add("active");
    }
  });

  // Cập nhật Tab Pane
  document.querySelectorAll(".tab-pane").forEach(pane => {
    pane.classList.remove("active");
  });
  const targetPane = document.getElementById(`tab-step-${stepNumber}`);
  if (targetPane) {
    targetPane.classList.add("active");
  }
}

// ==========================================
// 2. PILL GROUP CONTROLS
// ==========================================
function initPillSelectors() {
  document.querySelectorAll(".pill-group").forEach(group => {
    const options = group.querySelectorAll(".pill-option");
    options.forEach(opt => {
      opt.addEventListener("click", () => {
        options.forEach(o => o.classList.remove("active"));
        opt.classList.add("active");
      });
    });
  });
}

function getPillValue(groupId) {
  const group = document.getElementById(groupId);
  if (!group) return null;
  const active = group.querySelector(".pill-option.active");
  return active ? active.getAttribute("data-val") : null;
}

// ==========================================
// 3. SYSTEM APIS & HARDWARE DETECT
// ==========================================
async function initSystemAPIs() {
  try {
    const res = await fetch("/api/detect-encoders");
    const data = await res.json();

    // Foxglove Chip
    const foxgloveChip = document.getElementById("foxglove-status-chip");
    const foxgloveText = document.getElementById("foxglove-status-text");
    if (data.foxglove_found) {
      foxgloveChip.className = "status-badge foxglove-ready";
      foxgloveText.textContent = "Foxglove Studio Sẵn Sàng";
      foxgloveChip.title = data.foxglove_path;
    } else {
      foxgloveChip.className = "status-badge ready";
      foxgloveText.textContent = "Foxglove (Hỗ trợ mở file)";
    }

    // Encoder Selector Step 2
    const encoderSelect = document.getElementById("step2-encoder-select");
    if (encoderSelect && data.encoders) {
      encoderSelect.innerHTML = "";
      data.encoders.forEach(enc => {
        const opt = document.createElement("option");
        opt.value = enc.id;
        opt.textContent = enc.label;
        encoderSelect.appendChild(opt);
      });
    }
  } catch (err) {
    console.warn("Không thể phát hiện encoder/foxglove:", err);
  }

  // Nút Hủy Tác Vụ
  const btnCancel = document.getElementById("btn-cancel-task");
  btnCancel.addEventListener("click", async () => {
    if (confirm("Bạn có chắc chắn muốn dừng tác vụ đang thực thi không?")) {
      try {
        await fetch("/api/cancel-task", { method: "POST" });
      } catch (e) {
        console.error("Lỗi khi hủy tác vụ:", e);
      }
    }
  });
}

// Helper chọn thư mục Windows Explorer
async function pickFolder(title = "Chọn Thư Mục") {
  try {
    const res = await fetch("/api/pick-folder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    const data = await res.json();
    return data.path;
  } catch (e) {
    console.error("Lỗi mở picker:", e);
    return null;
  }
}

// Helper chọn file Windows Explorer
async function pickFile(title = "Chọn File", fileType = "video") {
  try {
    const res = await fetch("/api/pick-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, file_type: fileType }),
    });
    const data = await res.json();
    return data.path;
  } catch (e) {
    console.error("Lỗi mở file picker:", e);
    return null;
  }
}

// Helper mở explorer
async function openExplorer(path) {
  if (!path) return;
  try {
    await fetch("/api/open-explorer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
  } catch (e) {
    console.error("Lỗi mở explorer:", e);
  }
}

// Helper mở Foxglove (hỗ trợ 1 file hoặc danh sách nhiều file)
async function openFoxglove(target) {
  if (!target) return;
  const isArray = Array.isArray(target);
  if (isArray && target.length === 0) return;
  const payload = isArray
    ? { paths: target, path: target[0] || "" }
    : { path: target, paths: [target] };
  const desc = isArray ? `${target.length} tập tin` : target;

  try {
    appendTerminalLine(`[FOXGLOVE] Đang mở ${desc} trên Foxglove Studio...`, "info");
    const res = await fetch("/api/open-foxglove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data.success) {
      appendTerminalLine(`[CẢNH BÁO] Không thể mở trực tiếp Foxglove. Hãy kiểm tra cài đặt.`, "warning");
    }
  } catch (e) {
    console.error("Lỗi mở Foxglove:", e);
  }
}

// ==========================================
// 4. WEBSOCKET LOGS & TERMINAL
// ==========================================
function initWebSocket() {
  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${wsProtocol}//${window.location.host}/ws/logs`;
  let ws = null;

  function connect() {
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("WebSocket connected");
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "init") {
          if (msg.history && msg.history.length > 0) {
            msg.history.forEach(line => appendTerminalLine(line));
          }
          updateRunningState(msg.is_running, msg.task_name);
        } else if (msg.type === "log") {
          appendTerminalLine(msg.data);
          // Kiểm tra nếu thông báo kết thúc
          if (msg.data.includes("[HOÀN THÀNH THÀNH CÔNG]") || msg.data.includes("[KẾT THÚC CÓ LỖI]")) {
            updateRunningState(false, "");
          }
        }
      } catch (e) {
        appendTerminalLine(event.data);
      }
    };

    ws.onclose = () => {
      setTimeout(connect, 2000);
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  connect();
}

function updateRunningState(isRunning, taskName = "") {
  AppState.isTaskRunning = isRunning;
  const taskChip = document.getElementById("task-status-chip");
  const taskText = document.getElementById("task-status-text");
  const btnCancel = document.getElementById("btn-cancel-task");

  if (isRunning) {
    if (taskChip) taskChip.style.display = "inline-flex";
    if (taskText) taskText.textContent = taskName || "Đang xử lý…";
    if (btnCancel) btnCancel.style.display = "inline-flex";
  } else {
    if (taskChip) taskChip.style.display = "none";
    if (btnCancel) btnCancel.style.display = "none";
  }
}

function initTerminal() {
  // Không hiển thị live log trên giao diện theo yêu cầu
}

function appendTerminalLine(text, forcedClass = null) {
  // Ghi log vào console của trình duyệt, không hiển thị trên giao diện người dùng
  console.log(text);
}

// ==========================================
// 5. STEP 1: MCAP TO MP4
// ==========================================
function initStep1() {
  const btnBrowseSrc = document.getElementById("btn-browse-step1-src");
  const btnBrowseOut = document.getElementById("btn-browse-step1-out");
  const btnOpenFolder = document.getElementById("btn-open-step1-folder");
  const btnRun = document.getElementById("btn-run-step1");

  btnBrowseSrc.addEventListener("click", async () => {
    const folder = await pickFolder("Chọn Thư Mục MCAP Nguồn (Chứa các file part)");
    if (folder) {
      document.getElementById("step1-src-dir").value = folder;
      AppState.activeSessionDir = folder;
    }
  });

  btnBrowseOut.addEventListener("click", async () => {
    const folder = await pickFolder("Chọn Thư Mục Xuất MP4");
    if (folder) {
      document.getElementById("step1-out-dir").value = folder;
    }
  });

  btnOpenFolder.addEventListener("click", () => {
    const src = document.getElementById("step1-src-dir").value.trim();
    const out = document.getElementById("step1-out-dir").value.trim();
    openExplorer(out || src);
  });

  btnRun.addEventListener("click", async () => {
    const src = document.getElementById("step1-src-dir").value.trim();
    if (!src) {
      alert("Vui lòng nhập hoặc chọn thư mục MCAP nguồn!");
      return;
    }

    const camera = getPillValue("step1-camera-pills") || "both";
    const codec = getPillValue("step1-codec-pills") || "copy";
    const outDir = document.getElementById("step1-out-dir").value.trim() || null;

    try {
      btnRun.disabled = true;
      updateRunningState(true, `Trích xuất MP4 từ ${src}`);

      const res = await fetch("/api/step1/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mcap_dir: src,
          camera: camera,
          output_dir: outDir,
          h264: (codec === "h264"),
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Lỗi khởi chạy tác vụ");
      }
      appendTerminalLine(`[BẮT ĐẦU] Đã khởi chạy kịch bản trích xuất MP4...`, "info");
    } catch (e) {
      alert(`Lỗi: ${e.message}`);
      updateRunningState(false);
    } finally {
      btnRun.disabled = false;
    }
  });
}

// ==========================================
// 6. STEP 2: CAPCUT TO MCAP
// ==========================================
function initStep2() {
  const btnBrowseOrig = document.getElementById("btn-browse-step2-orig");
  const btnBrowseLeft = document.getElementById("btn-browse-step2-left");
  const btnBrowseRight = document.getElementById("btn-browse-step2-right");
  const btnBrowseOut = document.getElementById("btn-browse-step2-out");
  const btnOpenFolder = document.getElementById("btn-open-step2-folder");
  const btnRun = document.getElementById("btn-run-step2");

  btnBrowseOrig.addEventListener("click", async () => {
    const folder = await pickFolder("Chọn Thư Mục MCAP Gốc (Chứa các part ban đầu)");
    if (folder) {
      document.getElementById("step2-orig-dir").value = folder;
      if (!document.getElementById("step2-out-dir").value) {
        document.getElementById("step2-out-dir").value = `${folder}_repacked`;
      }
    }
  });

  btnBrowseLeft.addEventListener("click", async () => {
    const file = await pickFile("Chọn Video Top-Left Đã Xuất Từ CapCut (MP4)", "video");
    if (file) {
      document.getElementById("step2-video-left").value = file;
    }
  });

  btnBrowseRight.addEventListener("click", async () => {
    const file = await pickFile("Chọn Video Top-Right Đã Xuất Từ CapCut (MP4)", "video");
    if (file) {
      document.getElementById("step2-video-right").value = file;
    }
  });

  btnBrowseOut.addEventListener("click", async () => {
    const folder = await pickFolder("Chọn Thư Mục Xuất MCAP Repacked");
    if (folder) {
      document.getElementById("step2-out-dir").value = folder;
    }
  });

  btnOpenFolder.addEventListener("click", () => {
    const orig = document.getElementById("step2-orig-dir").value.trim();
    const out = document.getElementById("step2-out-dir").value.trim();
    openExplorer(out || orig);
  });

  btnRun.addEventListener("click", async () => {
    const orig = document.getElementById("step2-orig-dir").value.trim();
    if (!orig) {
      alert("Vui lòng chọn thư mục MCAP gốc!");
      return;
    }

    const videoLeft = document.getElementById("step2-video-left").value.trim() || null;
    const videoRight = document.getElementById("step2-video-right").value.trim() || null;
    const outDir = document.getElementById("step2-out-dir").value.trim() || null;
    const encoder = document.getElementById("step2-encoder-select").value || "auto";

    if (!videoLeft && !videoRight) {
      const confirmContinue = confirm("Bạn chưa chọn video đã sửa (Left hoặc Right). Kịch bản sẽ tự dò tìm video trong thư mục nguồn nếu có. Tiếp tục?");
      if (!confirmContinue) return;
    }

    try {
      btnRun.disabled = true;
      updateRunningState(true, `Nạp Video CapCut vào MCAP (${orig})`);

      const res = await fetch("/api/step2/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          original_mcap_dir: orig,
          video_left: videoLeft,
          video_right: videoRight,
          output_dir: outDir,
          encoder: encoder,
          reencode: false,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Lỗi khởi chạy tác vụ nạp video");
      }
      appendTerminalLine(`[BẮT ĐẦU] Đã khởi chạy nạp video CapCut vào MCAP...`, "info");
    } catch (e) {
      alert(`Lỗi: ${e.message}`);
      updateRunningState(false);
    } finally {
      btnRun.disabled = false;
    }
  });
}

// ==========================================
// 7. STEP 3: FOXGLOVE & PART SPLITTER
// ==========================================
function initStep3() {
  const btnBrowseDir = document.getElementById("btn-browse-step3-dir");
  const btnScan = document.getElementById("btn-scan-step3");
  const btnSuggest = document.getElementById("btn-suggest-segments");
  const btnAddSeg = document.getElementById("btn-add-segment");
  const btnToggleDrawer = document.getElementById("btn-toggle-parts-drawer");
  const btnOpenFirstPart = document.getElementById("btn-open-first-part-foxglove");
  const btnExecuteSplit = document.getElementById("btn-execute-split");

  btnBrowseDir.addEventListener("click", async () => {
    const folder = await pickFolder("Chọn Thư Mục Chứa Các Part MCAP Cần Tách");
    if (folder) {
      document.getElementById("step3-target-dir").value = folder;
      scanStep3Parts(folder);
    }
  });

  btnScan.addEventListener("click", () => {
    const dir = document.getElementById("step3-target-dir").value.trim();
    if (!dir) {
      alert("Vui lòng nhập hoặc chọn thư mục MCAP cần tách!");
      return;
    }
    scanStep3Parts(dir);
  });

  btnToggleDrawer.addEventListener("click", () => {
    const tableWrap = document.getElementById("parts-table-container");
    const arrow = document.getElementById("drawer-arrow");
    tableWrap.classList.toggle("open");
    arrow.textContent = tableWrap.classList.contains("open") ? "[Thu gọn]" : "[Xem chi tiết]";
  });

  btnSuggest.addEventListener("click", () => {
    if (!AppState.step3ScanData || !AppState.step3ScanData.suggested_segments) return;
    renderSegmentsList(AppState.step3ScanData.suggested_segments);
  });

  btnAddSeg.addEventListener("click", () => {
    addNewSegmentRow();
  });

  // Chọn / bỏ chọn tất cả part
  const selectAllCheckbox = document.getElementById("step3-select-all-parts");
  if (selectAllCheckbox) {
    selectAllCheckbox.addEventListener("change", (e) => {
      const isChecked = e.target.checked;
      const checkboxes = document.querySelectorAll(".part-select-chk");
      checkboxes.forEach(cb => {
        cb.checked = isChecked;
      });
      updateSelectedPartsCounter();
    });
  }

  // Nút mở các part đã chọn trên Foxglove
  const btnOpenSelected = document.getElementById("btn-open-selected-foxglove");
  if (btnOpenSelected) {
    btnOpenSelected.addEventListener("click", () => {
      const selectedPaths = getSelectedPartPaths();
      if (selectedPaths.length === 0) {
        alert("Vui lòng tích chọn ít nhất 1 part trong bảng!");
        return;
      }
      openFoxglove(selectedPaths);
    });
  }

  // Nút mở cả thư mục trên Foxglove
  const btnOpenFolder = document.getElementById("btn-open-folder-foxglove");
  const btnOpenFolderMain = document.getElementById("btn-open-folder-foxglove-main");
  const triggerFolderOpen = () => {
    const dir = document.getElementById("step3-target-dir").value.trim();
    if (!dir) {
      alert("Vui lòng chọn thư mục MCAP trước!");
      return;
    }
    openFoxglove(dir);
  };
  if (btnOpenFolder) btnOpenFolder.addEventListener("click", triggerFolderOpen);
  if (btnOpenFolderMain) btnOpenFolderMain.addEventListener("click", triggerFolderOpen);

  btnExecuteSplit.addEventListener("click", async () => {
    const dir = document.getElementById("step3-target-dir").value.trim();
    const segments = gatherSegmentsFromUI();

    if (!dir) {
      alert("Chưa chọn thư mục!");
      return;
    }
    if (segments.length === 0) {
      alert("Vui lòng cấu hình ít nhất một nhóm thư mục con!");
      return;
    }

    // Kiểm tra cảnh báo > 30 part
    const over30 = segments.filter(s => (s.end_part - s.start_part + 1) > 30);
    if (over30.length > 0) {
      const confirmed = confirm(`Có ${over30.length} nhóm vượt quá 30 part (~30 phút). Theo quy tắc cần tách dưới 30 phút. Bạn có chắc chắn muốn tiếp tục không?`);
      if (!confirmed) return;
    }

    const confirmAction = confirm(`Hệ thống sẽ thực hiện Di Chuyển (Move) các part vào ${segments.length} thư mục con trong:\n${dir}\n\nThao tác này di chuyển trực tiếp tức thì. Bạn có chắc chắn?`);
    if (!confirmAction) return;

    try {
      btnExecuteSplit.disabled = true;
      appendTerminalLine(`[BẮT ĐẦU] Đang di chuyển các part vào các thư mục con...`, "info");

      const res = await fetch("/api/step3/execute", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          dir_path: dir,
          segments: segments,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Lỗi khi tách thư mục");
      }

      appendTerminalLine(`[HOÀN THÀNH] Đã tách thành công! Di chuyển ${data.total_moved} parts vào:`, "success");
      data.created_subfolders.forEach(sf => {
        appendTerminalLine(`  [Tạo thư mục] ${sf.name}: ${sf.moved_parts} parts (part ${sf.start_part} -> ${sf.end_part})`, "success");
      });

      alert(`Tách thư mục thành công! Đã tạo ${data.created_subfolders.length} thư mục con.`);
      // Tự động quét lại để cập nhật
      scanStep3Parts(dir);
    } catch (e) {
      alert(`Lỗi: ${e.message}`);
    } finally {
      btnExecuteSplit.disabled = false;
    }
  });
}

function getSelectedPartPaths() {
  const checkboxes = document.querySelectorAll(".part-select-chk:checked");
  const paths = [];
  checkboxes.forEach(cb => {
    const p = cb.getAttribute("data-path");
    if (p) paths.push(p);
  });
  return paths;
}

function updateSelectedPartsCounter() {
  const selectedPaths = getSelectedPartPaths();
  const counterEl = document.getElementById("step3-selected-count");
  if (counterEl) {
    counterEl.textContent = selectedPaths.length;
  }
  const btnOpenSelected = document.getElementById("btn-open-selected-foxglove");
  if (btnOpenSelected) {
    btnOpenSelected.disabled = (selectedPaths.length === 0);
  }
}

async function scanStep3Parts(dirPath) {
  try {
    appendTerminalLine(`[QUÉT PART] Đang quét thư mục: ${dirPath}...`, "info");
    const res = await fetch("/api/step3/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dir_path: dirPath }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Lỗi khi quét thư mục");
    }

    AppState.step3ScanData = data;

    // Hiển thị dải thống kê
    document.getElementById("step3-stats-strip").style.display = "grid";
    document.getElementById("stat-total-parts").textContent = data.total_parts;
    document.getElementById("stat-total-duration").textContent = `~${data.total_parts} phút`;
    document.getElementById("stat-total-size").textContent = `${data.total_size_mb} MB (${(data.total_size_mb / 1024).toFixed(2)} GB)`;

    const gapEl = document.getElementById("stat-gaps-status");
    if (data.gaps && data.gaps.length > 0) {
      gapEl.className = "stat-value warn";
      gapEl.textContent = `Thiếu ${data.gaps.length} khoảng part!`;
      appendTerminalLine(`[CẢNH BÁO] Phát hiện part bị thiếu: ${JSON.stringify(data.gaps)}`, "warning");
    } else {
      gapEl.className = "stat-value ok";
      gapEl.textContent = "Liền mạch 100%";
    }

    // Hiển thị nút Foxglove & Tách
    const btnOpenFolderMain = document.getElementById("btn-open-folder-foxglove-main");
    if (btnOpenFolderMain) btnOpenFolderMain.disabled = (data.total_parts === 0);
    document.getElementById("btn-execute-split").disabled = (data.total_parts === 0);

    // Điền bảng Parts chi tiết
    renderPartsTable(data.parts);
    document.getElementById("step3-parts-drawer").style.display = "block";

    // Điền danh sách phân nhóm Segments
    document.getElementById("step3-segments-wrapper").style.display = "block";
    renderSegmentsList(data.suggested_segments);

    appendTerminalLine(`[QUÉT XONG] Tìm thấy ${data.total_parts} parts (${data.total_size_mb} MB).`, "success");
  } catch (e) {
    appendTerminalLine(`[LỖI QUÉT] ${e.message}`, "error");
    alert(`Lỗi quét part: ${e.message}`);
  }
}

function renderPartsTable(parts) {
  const tbody = document.getElementById("parts-table-tbody");
  tbody.innerHTML = "";

  const selectAll = document.getElementById("step3-select-all-parts");
  if (selectAll) selectAll.checked = false;
  updateSelectedPartsCounter();

  parts.forEach((p, idx) => {
    const tr = document.createElement("tr");

    // Checkbox column
    const tdCheck = document.createElement("td");
    tdCheck.style.textAlign = "center";
    const chk = document.createElement("input");
    chk.type = "checkbox";
    chk.className = "part-select-chk";
    chk.setAttribute("data-path", p.path);
    chk.style.accentColor = "var(--color-accent)";
    chk.style.cursor = "pointer";
    chk.addEventListener("change", () => {
      updateSelectedPartsCounter();
      if (selectAll) {
        const allCheckboxes = document.querySelectorAll(".part-select-chk");
        const allChecked = Array.from(allCheckboxes).every(c => c.checked);
        selectAll.checked = allChecked;
      }
    });
    tdCheck.appendChild(chk);

    const tdName = document.createElement("td");
    tdName.textContent = p.filename;
    tdName.style.fontFamily = "var(--font-mono)";

    const tdPart = document.createElement("td");
    tdPart.className = "num";
    tdPart.textContent = p.part_number !== null ? `#${p.part_number}` : "-";

    const tdDur = document.createElement("td");
    tdDur.className = "num";
    tdDur.textContent = `~${p.est_duration_min} phút`;

    const tdSize = document.createElement("td");
    tdSize.className = "num";
    tdSize.textContent = `${p.size_mb} MB`;

    const tdAction = document.createElement("td");
    tdAction.style.textAlign = "right";

    const btnFox = document.createElement("button");
    btnFox.className = "btn btn-foxglove btn-sm";
    btnFox.textContent = "Mở riêng part này";
    btnFox.title = "Mở duy nhất part này trên Foxglove Studio";
    btnFox.addEventListener("click", () => {
      openFoxglove(p.path);
    });

    tdAction.appendChild(btnFox);
    tr.appendChild(tdCheck);
    tr.appendChild(tdName);
    tr.appendChild(tdPart);
    tr.appendChild(tdDur);
    tr.appendChild(tdSize);
    tr.appendChild(tdAction);
    tbody.appendChild(tr);
  });
}

function renderSegmentsList(segments) {
  const container = document.getElementById("segments-list-body");
  container.innerHTML = "";

  segments.forEach((seg, idx) => {
    createSegmentRow(seg.name, seg.start_part, seg.end_part, idx + 1);
  });
}

function createSegmentRow(name, startPart, endPart, index) {
  const container = document.getElementById("segments-list-body");
  const row = document.createElement("div");
  row.className = "segment-item-row";

  // Cột 1: Tên folder con
  const colName = document.createElement("div");
  colName.className = "form-group";
  const labelName = document.createElement("label");
  labelName.className = "form-label";
  labelName.textContent = `Thư mục con P${index}:`;
  const inputName = document.createElement("input");
  inputName.type = "text";
  inputName.className = "input-control seg-name-input";
  inputName.value = name;
  inputName.style.background = "var(--bg-input)";
  inputName.style.border = "1px solid var(--border-subtle)";
  inputName.style.borderRadius = "var(--radius-sm)";
  colName.appendChild(labelName);
  colName.appendChild(inputName);

  // Cột 2: Start Part
  const colStart = document.createElement("div");
  colStart.className = "form-group";
  const labelStart = document.createElement("label");
  labelStart.className = "form-label";
  labelStart.textContent = "Từ Part:";
  const inputStart = document.createElement("input");
  inputStart.type = "number";
  inputStart.min = "0";
  inputStart.className = "input-control seg-start-input";
  inputStart.value = startPart;
  inputStart.style.background = "var(--bg-input)";
  inputStart.style.border = "1px solid var(--border-subtle)";
  inputStart.style.borderRadius = "var(--radius-sm)";
  colStart.appendChild(labelStart);
  colStart.appendChild(inputStart);

  // Cột 3: End Part
  const colEnd = document.createElement("div");
  colEnd.className = "form-group";
  const labelEnd = document.createElement("label");
  labelEnd.className = "form-label";
  labelEnd.textContent = "Đến Part:";
  const inputEnd = document.createElement("input");
  inputEnd.type = "number";
  inputEnd.min = "0";
  inputEnd.className = "input-control seg-end-input";
  inputEnd.value = endPart;
  inputEnd.style.background = "var(--bg-input)";
  inputEnd.style.border = "1px solid var(--border-subtle)";
  inputEnd.style.borderRadius = "var(--radius-sm)";
  colEnd.appendChild(labelEnd);
  colEnd.appendChild(inputEnd);

  // Cột 4: Badge & Duration
  const colBadge = document.createElement("div");
  colBadge.className = "form-group";
  const labelBadge = document.createElement("label");
  labelBadge.className = "form-label";
  labelBadge.textContent = "Thời lượng & Tiêu chuẩn:";
  const badge = document.createElement("div");
  colBadge.appendChild(labelBadge);
  colBadge.appendChild(badge);

  function updateBadge() {
    const s = parseInt(inputStart.value, 10) || 0;
    const e = parseInt(inputEnd.value, 10) || 0;
    const count = Math.max(0, e - s + 1);
    if (count <= 30) {
      badge.className = "segment-badge safe";
      badge.textContent = `${count} parts (~${count}p) - Đạt chuẩn ≤30p`;
    } else {
      badge.className = "segment-badge danger";
      badge.textContent = `${count} parts (~${count}p) - Cảnh báo > 30p`;
    }
  }

  inputStart.addEventListener("input", updateBadge);
  inputEnd.addEventListener("input", updateBadge);
  updateBadge();

  // Cột 5: Nút Xóa
  const colAction = document.createElement("div");
  colAction.style.paddingTop = "18px";
  const btnDelete = document.createElement("button");
  btnDelete.type = "button";
  btnDelete.className = "btn btn-danger btn-sm";
  btnDelete.textContent = "Xóa";
  btnDelete.title = "Xóa nhóm này";
  btnDelete.addEventListener("click", () => {
    row.remove();
  });
  colAction.appendChild(btnDelete);

  row.appendChild(colName);
  row.appendChild(colStart);
  row.appendChild(colEnd);
  row.appendChild(colBadge);
  row.appendChild(colAction);
  container.appendChild(row);
}

function addNewSegmentRow() {
  const container = document.getElementById("segments-list-body");
  const existingRows = container.querySelectorAll(".segment-item-row");
  const nextIdx = existingRows.length + 1;

  let nextStart = 0;
  if (existingRows.length > 0) {
    const lastEndInput = existingRows[existingRows.length - 1].querySelector(".seg-end-input");
    nextStart = (parseInt(lastEndInput.value, 10) || 0) + 1;
  }
  const nextEnd = nextStart + 24; // mặc định 25 parts (~25 phút)

  const folderName = (AppState.step3ScanData && AppState.step3ScanData.folder_name) || "SESSION";
  createSegmentRow(`${folderName}_P${nextIdx}`, nextStart, nextEnd, nextIdx);
}

function gatherSegmentsFromUI() {
  const container = document.getElementById("segments-list-body");
  const rows = container.querySelectorAll(".segment-item-row");
  const segments = [];

  rows.forEach(r => {
    const name = r.querySelector(".seg-name-input").value.trim();
    const start = parseInt(r.querySelector(".seg-start-input").value, 10);
    const end = parseInt(r.querySelector(".seg-end-input").value, 10);
    if (name && !isNaN(start) && !isNaN(end)) {
      segments.push({
        name: name,
        start_part: start,
        end_part: end,
      });
    }
  });

  return segments;
}

// ==========================================
// 8. STEP 4: BATCH MERGE MCAP
// ==========================================
function initStep4() {
  const btnBrowseDir = document.getElementById("btn-browse-step4-dir");
  const btnScan = document.getElementById("btn-scan-step4");
  const btnOpenFolder = document.getElementById("btn-open-step4-folder");
  const btnRun = document.getElementById("btn-run-step4");

  btnBrowseDir.addEventListener("click", async () => {
    const folder = await pickFolder("Chọn Thư Mục Cha Chứa Các Folder Con (_P1, _P2...)");
    if (folder) {
      document.getElementById("step4-parent-dir").value = folder;
      scanStep4Targets(folder);
    }
  });

  btnScan.addEventListener("click", () => {
    const dir = document.getElementById("step4-parent-dir").value.trim();
    if (!dir) {
      alert("Vui lòng nhập hoặc chọn thư mục cha!");
      return;
    }
    scanStep4Targets(dir);
  });

  btnOpenFolder.addEventListener("click", () => {
    const dir = document.getElementById("step4-parent-dir").value.trim();
    openExplorer(dir);
  });

  btnRun.addEventListener("click", async () => {
    if (!AppState.step4ScanData || AppState.step4ScanData.targets.length === 0) {
      alert("Chưa có thư mục con nào được quét!");
      return;
    }

    const compression = getPillValue("step4-compression-pills") || "zstd";
    const targets = AppState.step4ScanData.targets;

    const confirmAction = confirm(`Hệ thống sẽ tiến hành gộp MCAP cho ${targets.length} thư mục con.\nFile kết quả sẽ được tạo trực tiếp bên trong từng thư mục và giữ nguyên các part gốc.\n\nBắt đầu gộp?`);
    if (!confirmAction) return;

    try {
      btnRun.disabled = true;
      updateRunningState(true, `Gộp ${targets.length} thư mục MCAP`);

      const res = await fetch("/api/step4/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          targets: targets,
          compression: compression,
          chunk_size_mb: 4,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Lỗi khi bắt đầu gộp batch");
      }
      appendTerminalLine(`[BẮT ĐẦU] Đang thực hiện gộp ${data.targets_count} thư mục con trong luồng nền...`, "info");
    } catch (e) {
      alert(`Lỗi: ${e.message}`);
      updateRunningState(false);
    } finally {
      btnRun.disabled = false;
    }
  });
}

async function scanStep4Targets(parentPath) {
  try {
    appendTerminalLine(`[QUÉT BATCH] Đang quét các thư mục con trong: ${parentPath}...`, "info");
    const res = await fetch("/api/step4/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: [parentPath] }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Lỗi khi quét thư mục con");
    }

    AppState.step4ScanData = data;
    document.getElementById("step4-target-count").textContent = data.count;
    document.getElementById("step4-targets-wrapper").style.display = "block";
    document.getElementById("btn-run-step4").disabled = (data.count === 0);

    renderStep4Table(data.targets);
    appendTerminalLine(`[QUÉT XONG] Tìm thấy ${data.count} thư mục con có chứa part MCAP.`, "success");
  } catch (e) {
    appendTerminalLine(`[LỖI QUÉT BATCH] ${e.message}`, "error");
    alert(`Lỗi quét batch: ${e.message}`);
  }
}

function renderStep4Table(targets) {
  const tbody = document.getElementById("step4-targets-tbody");
  tbody.innerHTML = "";

  if (targets.length === 0) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.style.textAlign = "center";
    td.style.color = "var(--text-dim)";
    td.textContent = "Không tìm thấy thư mục con nào chứa part MCAP.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  targets.forEach(t => {
    const tr = document.createElement("tr");

    const tdName = document.createElement("td");
    tdName.innerHTML = `<strong>${t.name}</strong>`;

    const tdParts = document.createElement("td");
    tdParts.className = "num";
    tdParts.textContent = `${t.parts_count} parts`;

    const tdSize = document.createElement("td");
    tdSize.className = "num";
    tdSize.textContent = `${t.total_size_mb} MB`;

    const tdOutput = document.createElement("td");
    tdOutput.textContent = `${t.name}.mcap`;
    tdOutput.style.fontFamily = "var(--font-mono)";
    tdOutput.style.color = "var(--color-accent)";

    const tdStatus = document.createElement("td");
    if (t.already_merged) {
      tdStatus.innerHTML = `<span style="color: var(--color-success);">Đã có file gộp</span>`;
    } else {
      tdStatus.innerHTML = `<span style="color: var(--color-muted);">Chưa gộp</span>`;
    }

    tr.appendChild(tdName);
    tr.appendChild(tdParts);
    tr.appendChild(tdSize);
    tr.appendChild(tdOutput);
    tr.appendChild(tdStatus);
    tbody.appendChild(tr);
  });
}
