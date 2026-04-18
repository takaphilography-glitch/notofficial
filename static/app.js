// Debug: catch any global errors and show them
window.onerror = function(msg, url, line) {
  var s = document.getElementById("status");
  if (s) s.textContent = "JS Error: " + msg + " (line " + line + ")";
};

const dropZone = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
const statusEl = document.getElementById("status");
const downloadLink = document.getElementById("download-link");
const subtitleToggle = document.getElementById("subtitle-toggle");
const convertMode = document.getElementById("convert-mode");
const beautyToggle = document.getElementById("beauty-toggle");

function setStatus(message, type = "idle") {
  statusEl.textContent = message;
  statusEl.className = `status ${type}`;
}

function clearDownload() {
  downloadLink.classList.add("hidden");
  downloadLink.href = "#";
}

function isVideoFile(file) {
  if (file.type && file.type.startsWith("video/")) return true;
  const ext = file.name.split(".").pop().toLowerCase();
  return ["mp4", "mov", "mkv", "avi", "webm", "m4v", "3gp"].includes(ext);
}

async function uploadAndConvert(file) {
  if (!isVideoFile(file)) {
    setStatus("動画ファイルを選択してください。", "error");
    return;
  }
  const formData = new FormData();
  formData.append("video", file);
  formData.append("subtitle_enabled", subtitleToggle.checked ? "true" : "false");
  formData.append("convert_mode", convertMode.value);
  formData.append("beauty_enabled", beautyToggle.checked ? "true" : "false");

  if (subtitleToggle.checked) {
    setStatus("音声解析と変換中です... 少し時間がかかります。", "loading");
  } else {
    setStatus("字幕なしで変換中です...", "loading");
  }
  clearDownload();

  try {
    var response;
    try {
      response = await fetch("/convert", {
        method: "POST",
        body: formData,
      });
    } catch (networkErr) {
      throw new Error("サーバーに接続できません。しばらく待ってから再試行してください。");
    }

    var result;
    try {
      result = await response.json();
    } catch (parseErr) {
      throw new Error("サーバーエラーが発生しました（ステータス: " + response.status + "）");
    }

    if (!response.ok) {
      throw new Error(result.error || "変換処理に失敗しました。");
    }

    const serverMessage = result.message;
    if (serverMessage) {
      setStatus(`${serverMessage} ダウンロードできます。`, "success");
    } else if (subtitleToggle.checked) {
      setStatus("字幕付き縦動画の変換完了。ダウンロードできます。", "success");
    } else {
      setStatus("字幕なし縦動画の変換完了。ダウンロードできます。", "success");
    }
    downloadLink.href = result.download_url;
    downloadLink.classList.remove("hidden");
  } catch (error) {
    setStatus(error.message, "error");
  }
}

// label[for] handles click->file dialog natively, no JS click() needed
fileInput.addEventListener("change", (event) => {
  const file = event.target.files?.[0];
  if (file) {
    uploadAndConvert(file);
  }
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragover");
  const file = event.dataTransfer?.files?.[0];
  if (!file) {
    return;
  }
  uploadAndConvert(file);
});
