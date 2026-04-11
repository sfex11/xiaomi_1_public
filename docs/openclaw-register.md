---
layout: page
title: "OpenClaw 자동 등록"
permalink: /openclaw-register/
---

<p style="text-align:center;font-size:13px;color:#888;">이 페이지에 접속한 기기에서 아래 버튼을 누르면 자동으로 Chatub 관제탑에 등록됩니다.</p>

<div id="register-status" style="text-align:center;padding:20px;font-size:14px;">
  <button id="auto-register-btn" onclick="autoRegister()" style="padding:14px 32px;background:#007AFF;color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:700;cursor:pointer;">🚀 자동 등록 시작</button>
</div>

<div id="register-log" style="background:#1e1e1e;color:#e0e0e0;border-radius:12px;padding:16px;font-family:monospace;font-size:12px;max-height:400px;overflow-y:auto;display:none;margin-top:16px;white-space:pre-wrap;"></div>

<style>
  #auto-register-btn:hover { opacity: 0.85; }
  #auto-register-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>

<script>
const CHATUB_API = "http://129.154.63.231:8081";
const LOG_ID = "register-log";

function log(msg, type) {
  var el = document.getElementById(LOG_ID);
  el.style.display = "block";
  var color = type === "ok" ? "#4cd964" : type === "err" ? "#ff3b30" : type === "warn" ? "#ffcc00" : "#ccc";
  var prefix = type === "ok" ? "✅ " : type === "err" ? "❌ " : type === "warn" ? "⚠️ " : "🔍 ";
  el.innerHTML += '<span style="color:' + color + ';">' + prefix + msg + '</span>\n';
  el.scrollTop = el.scrollHeight;
}

async function autoRegister() {
  var btn = document.getElementById("auto-register-btn");
  btn.disabled = true;
  btn.textContent = "감지 중...";

  document.getElementById(LOG_ID).innerHTML = "";
  log("=== OpenClaw 자동 등록 시작 ===", "info");

  // Step 1: Detect hostname
  log("1/5 호스트네임 감지 중...", "info");
  var hostname = "";
  try {
    hostname = window.location.hostname;
    log("호스트네임: " + hostname, "ok");
  } catch(e) {
    log("호스트네임 감지 실패: " + e.message, "err");
    btn.disabled = false;
    btn.textContent = "🚀 자동 등록 시작";
    return;
  }

  // Step 2: Detect agent name from OpenClaw
  log("2/5 에이전트 이름 감지 중...", "info");
  var agentName = hostname.split(".")[0] || "agent-" + Math.random().toString(36).substr(2, 4);
  log("에이전트 이름: " + agentName + " (호스트네임에서 추출)", "ok");

  // Step 3: Gateway 정보 입력 안내
  log("3/5 Gateway 정보 확인", "info");
  log("이 페이지를 여는 기기의 Gateway 정보가 필요합니다.", "info");

  // Try to detect if we're on the same network
  var gatewayUrl = prompt(
    "OpenClaw Gateway 주소를 입력하세요.\n" +
    "예시:\n" +
    "  http://192.168.0.110:18789 (레노버)\n" +
    "  http://192.168.0.109:18789 (샤오미)\n" +
    "  http://192.168.0.101:18789 (라이카)\n\n" +
    "또는 이 기기의 Gateway 주소:",
    "http://127.0.0.1:18789"
  );

  if (!gatewayUrl) {
    log("사용자 취소", "warn");
    btn.disabled = false;
    btn.textContent = "🚀 자동 등록 시작";
    return;
  }
  log("Gateway URL: " + gatewayUrl, "ok");

  // Step 4: Gateway 토큰
  var token = prompt("Gateway 토큰을 입력하세요 (없으면 빈칸):", "");
  if (token === null) token = "";
  log("토큰: " + (token ? "****" + token.slice(-4) : "(없음)"), "ok");

  // Step 5: Register
  log("4/5 Chatub에 등록 중...", "info");
  try {
    var resp = await fetch(CHATUB_API + "/api/gateways/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: agentName,
        url: gatewayUrl,
        token: token
      })
    });
    var data = await resp.json();

    if (data.ok) {
      var health = data.data.health || {};
      log("5/5 등록 완료!", "ok");
      log("", "info");
      log("┌─────────────────────────────┐", "ok");
      log("│  🎉 등록 성공!              │", "ok");
      log("│  이름: " + agentName, "ok");
      log("│  URL:  " + gatewayUrl, "ok");
      log("│  상태: " + (health.online ? "🟢 온라인" : "🔴 오프라인"), health.online ? "ok" : "warn");
      log("│  버전: " + (health.version || "N/A"), "ok");
      log("└─────────────────────────────┘", "ok");
      log("", "info");
      log("Chatub 관제탑에서 확인하세요:", "info");
      log(CHATUB_API, "info");
      btn.textContent = "✅ 등록 완료!";
    } else {
      log("등록 실패: " + (data.error || "알 수 없는 오류"), "err");
      btn.disabled = false;
      btn.textContent = "🚀 다시 시도";
    }
  } catch(e) {
    log("네트워크 오류: " + e.message, "err");
    log("Chatub 서버가 실행 중인지 확인하세요: " + CHATUB_API, "warn");
    btn.disabled = false;
    btn.textContent = "🚀 다시 시도";
  }
}
</script>
