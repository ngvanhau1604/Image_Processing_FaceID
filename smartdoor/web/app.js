"use strict";
const el = (id) => document.getElementById(id);
let people = [],
  devices = [],
  historyRows = [],
  editing = null,
  version = 0;
const reasons = {
  authorized: "Có quyền",
  permission_denied: "Đã nhận diện · chưa có quyền",
  unknown: "Không đủ độ tin cậy",
  manual: "Quản trị mở thử",
  no_face: "Không có mặt",
  multiple_faces: "Nhiều khuôn mặt",
  wait_until_clear: "Chờ rời khung hình",
  ai_unavailable: "Mô hình chưa sẵn sàng",
  invalid_jpeg: "Ảnh không hợp lệ",
  small: "Hãy tiến gần camera",
  blurry: "Ảnh mờ",
  dark: "Thiếu sáng",
  overexposed: "Quá sáng",
  low_detail: "Mặt thiếu chi tiết",
  calibration_required: "Cần hiệu chỉnh camera",
  sample_collected: "Đã nhận mẫu",
  duplicate_sample: "Mẫu trùng",
  enrollment_complete: "Đã hoàn tất bộ mẫu",
  processing_timeout: "Quá thời hạn xử lý",
};
const execution = {
  pending: "Đã cấp lệnh, chưa có xác nhận",
  started: "Thiết bị báo đã kích",
  stopped: "Thiết bị báo đã ngắt",
};
const states = { GRANTED: "Cấp lệnh", DENIED: "Giữ khóa", ERROR: "Lỗi" };
const deviceName = (d) =>
  d.simulated ? "Webcam · thiết bị giả lập" : "ESP32-S3 N16R8 · OV3660 · LY-03";
const msg = (text) => {
  el("message").textContent = text;
};
function signedIn(active) {
  el("login").hidden = active;
  el("workspace").hidden = !active;
  el("logout").hidden = !active;
}
async function api(path, method = "GET", body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const r = await fetch("/api/v1/" + path, options);
  if (r.status === 401) signedIn(false);
  if (!r.ok) {
    const data = await r.json().catch(() => ({}));
    throw Error(
      typeof data.detail === "string" ? data.detail : "Yêu cầu không hợp lệ",
    );
  }
  return r.json();
}
function action(fn) {
  return async (event) => {
    event.preventDefault();
    try {
      await fn();
    } catch (e) {
      msg(e.message);
    }
  };
}
function cells(parent, values) {
  const row = parent.insertRow();
  for (const v of values) row.insertCell().textContent = v;
  return row;
}
function button(cell, label, fn) {
  const b = document.createElement("button");
  b.textContent = label;
  b.onclick = action(fn);
  cell.append(b);
}
function selectOptions(select, pairs) {
  const old = select.value;
  select.replaceChildren(...pairs.map(([v, t]) => new Option(t, v)));
  if (pairs.some(([v]) => String(v) === old)) select.value = old;
}
function render() {
  selectOptions(
    el("device"),
    devices.map((d) => [d.id, deviceName(d)]),
  );
  selectOptions(
    el("subject"),
    people.filter((p) => p.consent).map((p) => [p.id, p.name + " · " + p.code]),
  );
  const device = devices.find((d) => d.id === el("device").value);
  if (!device) return;
  el("connection").textContent = device.online ? "Đang kết nối" : "Ngoại tuyến";
  el("hardwareState").textContent =
    deviceName(device) + " · " + el("connection").textContent;
  el("calibration").textContent = device.simulated
    ? "Relay mô phỏng trên laptop"
    : device.profile
      ? "Đã hiệu chỉnh cho thiết bị"
      : "Chờ hiệu chỉnh bằng camera thực";
  el("manual").disabled = !device.online || Boolean(device.person);
  el("progress").textContent = device.person
    ? "Đang thu mẫu: " + device.collected + "/" + device.target
    : "Chưa có phiên thu đang chạy";
  const events = historyRows.filter((r) => r.device === device.id);
  el("feedback").textContent = events.length
    ? "Lần gần nhất: " + (reasons[events[0].reason] || events[0].reason)
    : "";
  el("people").replaceChildren();
  for (const p of people) {
    const allowed = p.devices.includes(device.id);
    const row = cells(el("people"), [
      p.name + " · " + p.code,
      p.consent ? "Có" : "Chưa",
      p.samples,
      allowed ? "Được phép" : "Chưa cấp",
    ]);
    const ops = row.insertCell();
    button(ops, "Sửa", () => {
      editing = p.id;
      el("code").value = p.code;
      el("name").value = p.name;
      el("consent").checked = !!p.consent;
      el("save").textContent = "Lưu";
      el("cancelEdit").hidden = false;
      el("name").focus();
    });
    if (p.consent)
      button(ops, allowed ? "Thu hồi" : "Cấp quyền", async () => {
        await api("people/" + p.id + "/permission", "PUT", {
          device: device.id,
          allowed: !allowed,
        });
        await refresh();
      });
  }
  el("events").replaceChildren();
  for (const e of events)
    cells(el("events"), [
      new Date(e.time).toLocaleString("vi-VN"),
      deviceName(device),
      e.name || "—",
      states[e.decision],
      reasons[e.reason] || e.reason,
      (execution[e.execution] || "—") +
        (e.pulse_ms !== null ? " · " + e.pulse_ms + " ms" : ""),
    ]);
}
async function refresh() {
  const seq = ++version;
  const rows = await Promise.all([
    api("people"),
    api("devices/health"),
    api("access/events"),
  ]);
  if (seq !== version) return;
  [people, devices, historyRows] = rows;
  signedIn(true);
  render();
}
function resetForm() {
  editing = null;
  el("personForm").reset();
  el("save").textContent = "Thêm người dùng";
  el("cancelEdit").hidden = true;
}
el("login").onsubmit = action(async () => {
  await api("login", "POST", {
    username: el("username").value,
    password: el("password").value,
  });
  el("password").value = "";
  msg("");
  await refresh();
});
el("logout").onclick = action(async () => {
  await api("logout", "POST");
  ++version;
  signedIn(false);
  resetForm();
  msg("");
});
el("personForm").onsubmit = action(async () => {
  const person = {
    code: el("code").value,
    name: el("name").value,
    consent: el("consent").checked,
  };
  if (
    editing &&
    people.find((p) => p.id === editing)?.consent &&
    !person.consent &&
    !confirm("Rút đồng ý sẽ xóa mẫu khuôn mặt và thu hồi mọi quyền. Tiếp tục?")
  )
    return;
  await api(
    editing ? "people/" + editing : "people",
    editing ? "PUT" : "POST",
    person,
  );
  resetForm();
  msg("Đã lưu hồ sơ.");
  await refresh();
});
el("cancelEdit").onclick = resetForm;
el("device").onchange = render;
el("enrollForm").onsubmit = action(async () => {
  await api("enrollments", "POST", {
    device: el("device").value,
    person: Number(el("subject").value),
    samples: Number(el("count").value),
  });
  msg("Đã mở phiên thu mẫu.");
  await refresh();
});
el("cancelSession").onclick = action(async () => {
  await api("enrollments/" + el("device").value, "DELETE");
  msg("Đã hủy phiên thu.");
  await refresh();
});
el("manual").onclick = action(async () => {
  if (!confirm("Gửi lệnh mở thử cho thiết bị đang chọn?")) return;
  await api("access/manual-unlock", "POST", { device: el("device").value });
  msg("Đã yêu cầu mở thử. Xem xác nhận trong lịch sử.");
});
for (const b of document.querySelectorAll("nav button"))
  b.onclick = () => {
    for (const n of document.querySelectorAll("nav button")) {
      el(n.dataset.page).hidden = n !== b;
      n.setAttribute("aria-current", n === b ? "page" : "false");
    }
  };
document.querySelector("nav button").click();
refresh().catch(() => signedIn(false));
setInterval(() => {
  if (!el("workspace").hidden) refresh().catch((e) => msg(e.message));
}, 2000);
