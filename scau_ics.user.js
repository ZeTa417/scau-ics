// ==UserScript==
// @name         华农课表导出 ICS
// @namespace    scau-ics
// @version      0.3.0
// @description  在华南农业大学教务系统个人课表页添加“导出课表 ICS”按钮
// @match        *://jwxt.scau.edu.cn/*
// @match        *://jwzf.scau.edu.cn/*
// @grant        none
// ==/UserScript==

(function () {
  "use strict";

  var calendarStart = null; // 学期第一周周一 0 点的时间戳（毫秒）
  var semesterName = "";
  var classData = null;
  var oldSystem = location.hostname.indexOf("jwzf") >= 0;

  // 华南农业大学 2026-2027 学年官方作息时间（每节 40 分钟）
  var SECTION_TIMES = [
    ["08:00", "08:40"],
    ["08:45", "09:25"],
    ["09:55", "10:35"],
    ["10:40", "11:20"],
    ["11:25", "12:05"],
    ["12:40", "13:20"],
    ["13:25", "14:05"],
    ["14:30", "15:10"],
    ["15:15", "15:55"],
    ["16:25", "17:05"],
    ["17:10", "17:50"],
    ["17:55", "18:35"],
    ["19:30", "20:10"],
    ["20:15", "20:55"],
    ["21:00", "21:40"]
  ];

  function parseOldWeeks(raw) {
    var text = String(raw || "").replace(/周/g, "").trim();
    var result = [];
    String(text).split(/[,，;；]/).forEach(function (part) {
      part = part.trim();
      if (!part) return;
      var parity = 1;
      var pm = part.match(/^(.+?)[（(](单|双)[）)]$/);
      if (pm) {
        part = pm[1];
        parity = pm[2] === "单" ? 2 : 3;
      }
      var m = part.match(/^(\d+)-(\d+)$/);
      var start, end;
      if (m) {
        start = parseInt(m[1], 10);
        end = parseInt(m[2], 10);
      } else if (/^\d+$/.test(part)) {
        start = end = parseInt(part, 10);
      } else {
        return;
      }
      for (var w = start; w <= end; w++) {
        if (parity === 2 && w % 2 === 0) continue;
        if (parity === 3 && w % 2 === 1) continue;
        if (result.indexOf(w) < 0) result.push(w);
      }
    });
    return result;
  }

  function oldSectionNumbers(jc) {
    var text = String(jc || "").replace(/节/g, "").trim();
    var m = text.match(/^(\d+)\s*[-—~至到]\s*(\d+)$/);
    if (m) return [parseInt(m[1], 10), parseInt(m[2], 10)];
    var n = parseInt(text, 10);
    return [n || 1, n || 1];
  }

  function oldSectionTime(jc, end) {
    var nums = oldSectionNumbers(jc);
    var first = Math.min(nums[0], nums[1]);
    var last = Math.max(nums[0], nums[1]);
    var from = SECTION_TIMES[first - 1] || SECTION_TIMES[0];
    var to = SECTION_TIMES[last - 1] || SECTION_TIMES[0];
    return end ? to[1] : from[0];
  }

  function normalizeOldCourse(course) {
    return {
      id: course.jxb_id || course.kch_id || (course.kcmc + "_" + course.xqj + "_" + course.zcd + "_" + course.jc),
      kc_name: course.kcmc || "未命名课程",
      fzmc_name: course.fzmc_name || course.kcxzmc || "",
      arrange_num: "1",
      xslx_name1: course.kcxz || "",
      pkzc_1: String(course.zcd || ""),
      sjbzcode: "1",
      pksj: course.xqjmc || course.xqj,
      djkssj: oldSectionTime(course.jc, false),
      djjssj: oldSectionTime(course.jc, true),
      teachernames: course.xm || "",
      ktmc_name: course.xm || "",
      js_name_1: course.cdmc || "",
      __weekList: parseOldWeeks(course.zcd)
    };
  }

  function handleResponse(url, text) {
    if (url.indexOf("findWeekCalendarList") >= 0) {
      try {
        var body = JSON.parse(text);
        var list = extractList(body);
        if (list && list.length && list[0].rq) {
          calendarStart = Number(list[0].rq);
          semesterName = list[0].xnxq || list[0].xnxqmc || list[0].name || semesterName;
        }
      } catch (e) {}
    } else if (url.indexOf("searchOneXskbList") >= 0) {
      try {
        var body = JSON.parse(text);
        var data = body && typeof body === "object" && "data" in body ? body.data : body;
        if (Array.isArray(data) && data.length && data[0].kc_name) {
          classData = data;
        }
      } catch (e) {}
    } else if (url.indexOf("xskbcx_cxXsgrkb") >= 0) {
      try {
        var body = JSON.parse(text);
        var list = body && typeof body === "object" && "kbList" in body ? body.kbList : null;
        if (Array.isArray(list) && list.length) {
          classData = list.map(normalizeOldCourse);
          if (body.xnxqmc) semesterName = body.xnxqmc;
        }
      } catch (e) {}
    }
  }

  function extractList(body) {
    var data = body && typeof body === "object" && "data" in body ? body.data : body;
    if (Array.isArray(data)) return data;
    if (data && typeof data === "object") {
      var keys = ["jxzllist", "xnxqlist", "list", "items", "rows"];
      for (var i = 0; i < keys.length; i++) {
        if (Array.isArray(data[keys[i]]) && data[keys[i]].length) return data[keys[i]];
      }
    }
    return null;
  }

  function patchXhr() {
    var origOpen = XMLHttpRequest.prototype.open;
    var origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url) {
      this.__scauUrl = url || "";
      return origOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function () {
      var xhr = this;
      this.addEventListener("load", function () {
        if (xhr.status !== 200) return;
        var url = String(xhr.__scauUrl || "");
        handleResponse(url, xhr.responseText);
      });
      return origSend.apply(this, arguments);
    };
  }

  function patchFetch() {
    if (!window.fetch || window.__scauFetchPatched) return;
    var origFetch = window.fetch;
    window.__scauFetchPatched = true;
    window.fetch = function () {
      var input = arguments[0];
      var url = typeof input === "string" ? input : (input && input.url) || "";
      return origFetch.apply(this, arguments).then(function (response) {
        if (response && response.status === 200 && response.clone) {
          response.clone().text().then(function (text) {
            handleResponse(url, text);
          }).catch(function () {});
        }
        return response;
      });
    };
  }

  function pad(n) {
    return n < 10 ? "0" + n : "" + n;
  }

  function toHm(value) {
    if (value === null || value === undefined) return "00:00";
    var s = String(value).trim();
    if (s.indexOf(":") >= 0) {
      var parts = s.split(":");
      return pad(parseInt(parts[0], 10) || 0) + ":" + pad(parseInt(parts[1], 10) || 0);
    }
    if (/^\d{3}$/.test(s)) s = "0" + s;
    if (/^\d{4}$/.test(s)) return s.slice(0, 2) + ":" + s.slice(2, 4);
    return "00:00";
  }

  function weekdayOf(pksj) {
    var text = String(pksj || "").trim();
    if (/^(周|星期)/.test(text)) {
      var map = { "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7 };
      for (var i = 1; i < text.length; i++) {
        if (map[text.charAt(i)]) return map[text.charAt(i)];
      }
    }
    var m = text.match(/^([1-7])/) || text.match(/([1-7])/);
    return m ? parseInt(m[1], 10) : null;
  }

  function weeksOf(course) {
    if (course.__weekList && course.__weekList.length) {
      return course.__weekList.map(function (w) { return [w, w]; });
    }
    var raw = String(course.pkzc_1 || course.pkzc || "");
    if (!raw) return [];
    var result = [];
    raw.split(",").forEach(function (part) {
      part = part.trim();
      if (!part) return;
      var m = part.match(/^(\d+)-(\d+)$/);
      if (m) {
        result.push([parseInt(m[1], 10), parseInt(m[2], 10)]);
      } else if (/^\d+$/.test(part)) {
        var w = parseInt(part, 10);
        result.push([w, w]);
      }
    });
    return result;
  }

  function keepWeek(course, week) {
    if (course.__weekList) return true;
    var code = String(course.sjbzcode || "1");
    if (code === "2") return week % 2 === 1;
    if (code === "3") return week % 2 === 0;
    return true;
  }

  function escapeIcs(text) {
    return String(text == null ? "" : text)
      .replace(/\\/g, "\\\\")
      .replace(/;/g, "\\;")
      .replace(/,/g, "\\,")
      .replace(/\r\n/g, "\\n")
      .replace(/\n/g, "\\n")
      .replace(/\r/g, "\\n");
  }

  function className(course) {
    var title = String(course.kc_name || "未命名课程").trim();
    if (String(course.arrange_num || "1") !== "1") title += "(" + (course.xslx_name1 || "") + ")";
    if (course.fzmc_name) title += "[" + course.fzmc_name + "]";
    return title;
  }

  function buildIcs() {
    if (!calendarStart || !classData || !classData.length) return null;
    var startSec = calendarStart > 10000000000 ? calendarStart / 1000 : calendarStart;
    var startDate = new Date(startSec * 1000);
    var events = [];
    var uid = 0;

    classData.forEach(function (course) {
      var title = className(course);
      var location = String(course.js_name_1 || course.js_name || "").trim();
      var day = weekdayOf(course.pksj);
      if (!day) return;
      var startHm = toHm(course.djkssj || course.idjkssj);
      var endHm = toHm(course.djjssj || course.idjjssj);
      var weeks = weeksOf(course);

      weeks.forEach(function (range) {
        for (var week = range[0]; week <= range[1]; week++) {
          if (!keepWeek(course, week)) continue;
          var d = new Date(startDate.getTime());
          d.setDate(d.getDate() + (week - 1) * 7 + (day - 1));
          var sh = startHm.split(":");
          var eh = endHm.split(":");
          var start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), parseInt(sh[0], 10), parseInt(sh[1], 10));
          var end = new Date(d.getFullYear(), d.getMonth(), d.getDate(), parseInt(eh[0], 10), parseInt(eh[1], 10));
          if (end <= start) end = new Date(start.getTime() + 40 * 60000);
          uid++;
          events.push({
            uid: "scau-" + (course.id || uid) + "-" + week + "-" + uid,
            start: start,
            end: end,
            title: title,
            desc: "第" + week + "周 | " + (course.teachernames || "") + " | " + (course.ktmc_name || ""),
            location: location
          });
        }
      });
    });

    if (!events.length) return null;

    function fmt(d) {
      return d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + "T" + pad(d.getHours()) + pad(d.getMinutes()) + pad(d.getSeconds());
    }

    var lines = [
      "BEGIN:VCALENDAR",
      "PRODID:-//SCAU//Course Schedule//CN",
      "VERSION:2.0",
      "CALSCALE:GREGORIAN",
      "METHOD:PUBLISH",
      "X-WR-CALNAME:" + escapeIcs(semesterName + "课表"),
      "BEGIN:VTIMEZONE",
      "TZID:Asia/Shanghai",
      "BEGIN:STANDARD",
      "DTSTART:19700101T000000",
      "TZOFFSETFROM:+0800",
      "TZOFFSETTO:+0800",
      "END:STANDARD",
      "END:VTIMEZONE"
    ];
    events.forEach(function (ev) {
      lines.push("BEGIN:VEVENT");
      lines.push("UID:" + ev.uid);
      lines.push("DTSTAMP;TZID=Asia/Shanghai:" + fmt(new Date()));
      lines.push("DTSTART;TZID=Asia/Shanghai:" + fmt(ev.start));
      lines.push("DTEND;TZID=Asia/Shanghai:" + fmt(ev.end));
      lines.push("SUMMARY:" + escapeIcs(ev.title));
      lines.push("DESCRIPTION:" + escapeIcs(ev.desc));
      if (ev.location) lines.push("LOCATION:" + escapeIcs(ev.location));
      lines.push("END:VEVENT");
    });
    lines.push("END:VCALENDAR");
    return lines.join("\r\n") + "\r\n";
  }

  function download() {
    var ics = buildIcs();
    if (!ics && classData && classData.length && !calendarStart) {
      var saved = "";
      try { saved = localStorage.getItem("scau_ics_start") || ""; } catch (e) {}
      var dateStr = prompt(
        "请填写本学期第 1 周周一的日期（格式：2026-09-01）",
        saved || "2026-09-01"
      );
      if (!dateStr) return;
      var dm = dateStr.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
      if (!dm) {
        alert("日期格式不对，请用 2026-09-01 这样的格式。");
        return;
      }
      calendarStart = new Date(parseInt(dm[1], 10), parseInt(dm[2], 10) - 1, parseInt(dm[3], 10)).getTime();
      try { localStorage.setItem("scau_ics_start", dateStr); } catch (e) {}
      ics = buildIcs();
    }
    if (!ics) {
      alert("还没有获取到课表数据。请先进入“我的选课 → 个人课表”并刷新，等课表加载后再点导出。");
      return;
    }
    var blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = (semesterName || "课表") + ".ics";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () {
      URL.revokeObjectURL(url);
      a.remove();
    }, 1000);
  }

  function addButton() {
    if (document.getElementById("scau-ics-export")) return;
    var btn = document.createElement("button");
    btn.id = "scau-ics-export";
    btn.textContent = "导出课表 ICS";
    btn.style.cssText =
      "position:fixed;top:120px;right:20px;z-index:99999;" +
      "background:#2563eb;color:#fff;border:0;border-radius:6px;" +
      "padding:10px 16px;font-size:14px;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.2);";
    btn.addEventListener("click", download);
    document.body.appendChild(btn);
  }

  patchXhr();
  patchFetch();
  window.addEventListener("load", function () {
    addButton();
    setInterval(function () {
      if (!document.getElementById("scau-ics-export")) addButton();
    }, 2000);
  });
})();
