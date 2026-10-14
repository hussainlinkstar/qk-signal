(function () {
  var script = document.currentScript;
  if (!script) {
    return;
  }

  var apiKey = (script.getAttribute("data-api-key") || "").trim();
  var theme = (script.getAttribute("data-theme") || "dark").toLowerCase();
  var buttonText = (script.getAttribute("data-button-text") || "Get Your Free SEO Score").trim();
  var apiBaseAttr = (script.getAttribute("data-api-base") || "").trim();
  var targetId = (script.getAttribute("data-target-id") || "thothgraph-audit-widget").trim();
  var captchaSiteKey = (script.getAttribute("data-captcha-site-key") || "").trim();
  var normalizedApiKey = apiKey.toLowerCase();
  var invalidApiKeyPlaceholders = {
    stx_embed_your_key: true,
    replace_with_new_embed_key: true,
    replace_with_embed_key: true,
    your_embed_key: true,
  };

  var apiBase = apiBaseAttr;
  if (!apiBase) {
    try {
      apiBase = new URL(script.src).origin;
    } catch (_error) {
      apiBase = "";
    }
  }
  apiBase = apiBase.replace(/\/$/, "");

  var root = document.getElementById(targetId);
  if (!root) {
    root = document.createElement("div");
    root.id = targetId;
    script.parentNode.insertBefore(root, script.nextSibling);
  }

  var classPrefix = "stx-widget-" + targetId.replace(/[^a-z0-9_-]/gi, "-").toLowerCase();
  var isLightTheme = theme === "light";
  var palette = {
    surface: "#00040e",
    surfaceBorder: "rgba(79,70,229,.48)",
    text: "#f8fafc",
    mutedText: "#a1a1aa",
    inputBg: "rgba(9,9,11,.92)",
    inputBorder: "#0F172A",
    inputText: "#f8fafc",
    placeholder: "#64748b",
    statusBg: "rgba(79,70,229,.2)",
    statusText: "#c7d2fe",
    errorBg: "rgba(248,113,113,.16)",
    errorText: "#fecaca",
    scoreBg: "rgba(6,182,212,.18)",
    scoreBorder: "rgba(6,182,212,.36)",
    scoreText: "#99f6e4",
    shadow: "0 28px 60px rgba(2,6,23,.56)",
  };
  var styleId = classPrefix + "-style";
  if (!document.getElementById(styleId)) {
    var styles = document.createElement("style");
    styles.id = styleId;
    styles.textContent = [
      "." +
        classPrefix +
        "{position:relative;overflow:hidden;max-width:560px;padding:22px;border:1px solid " +
        palette.surfaceBorder +
        ";border-radius:20px;background:" +
        palette.surface +
        ";color:" +
        palette.text +
        ";font-family:Manrope,Inter,Arial,sans-serif;box-shadow:" +
        palette.shadow +
        ";}",
      "." +
        classPrefix +
        "::before{content:'';position:absolute;left:0;top:0;height:3px;width:100%;background:linear-gradient(90deg,#FF4D2D 0%,#14B8A6 100%);}",
      "." +
        classPrefix +
        "::after{content:'';position:absolute;right:-70px;top:-60px;width:180px;height:180px;border-radius:999px;background:radial-gradient(circle,rgba(79,70,229,.28) 0%,rgba(79,70,229,0) 72%);pointer-events:none;}",
      "." + classPrefix + " *{box-sizing:border-box;}",
      "." + classPrefix + " .stx-header{margin-bottom:14px;position:relative;z-index:1;}",
      "." +
        classPrefix +
        " .stx-kicker{display:inline-flex;align-items:center;margin-bottom:8px;padding:4px 10px;border-radius:999px;background:rgba(79,70,229,.14);border:1px solid rgba(79,70,229,.34);font-size:10px;line-height:1;letter-spacing:.16em;text-transform:uppercase;font-weight:700;color:#c7d2fe;}",
      "." +
        classPrefix +
        " h3{margin:0;font-size:50px;line-height:.95;font-weight:800;letter-spacing:-.025em;}",
      "." +
        classPrefix +
        " p{margin:9px 0 0;font-size:15px;line-height:1.45;color:" +
        palette.mutedText +
        ";}",
      "." + classPrefix + " .stx-field{display:block;margin-top:11px;}",
      "." +
        classPrefix +
        " label{display:flex;justify-content:space-between;align-items:center;margin:0 0 7px;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-field-optional{font-size:10px;letter-spacing:.04em;text-transform:none;opacity:.88;}",
      "." +
        classPrefix +
        " input,." +
        classPrefix +
        " select{width:100%;height:50px;padding:0 14px;border-radius:13px;border:1px solid " +
        palette.inputBorder +
        ";background:" +
        palette.inputBg +
        ";color:" +
        palette.inputText +
        ";font-size:16px;line-height:1;transition:border-color .18s ease,box-shadow .18s ease,transform .18s ease;}",
      "." +
        classPrefix +
        " select{appearance:none;background-image:linear-gradient(45deg,transparent 50%,#a1a1aa 50%),linear-gradient(135deg,#a1a1aa 50%,transparent 50%);background-position:calc(100% - 20px) calc(50% - 2px),calc(100% - 14px) calc(50% - 2px);background-size:6px 6px,6px 6px;background-repeat:no-repeat;padding-right:38px;}",
      "." + classPrefix + " input::placeholder{color:" + palette.placeholder + ";}",
      "." +
        classPrefix +
        " input:focus,." +
        classPrefix +
        " select:focus{outline:none;border-color:#FF4D2D;box-shadow:0 0 0 3px rgba(47,107,255,.24);transform:translateY(-1px);}",
      "." +
        classPrefix +
        " input:disabled,." +
        classPrefix +
        " select:disabled{opacity:.72;cursor:not-allowed;}",
      "." +
        classPrefix +
        " button{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;margin-top:14px;border:0;border-radius:13px;padding:14px 14px;font-size:16px;font-weight:800;line-height:1;letter-spacing:.01em;color:#f8fafc;background:linear-gradient(92deg,#FF4D2D 0%,#14B8A6 100%);cursor:pointer;transition:transform .15s ease,box-shadow .15s ease,filter .15s ease;}",
      "." +
        classPrefix +
        " button:hover{transform:translateY(-1px);filter:brightness(1.03);box-shadow:0 12px 26px rgba(79,70,229,.32);}",
      "." +
        classPrefix +
        " button:focus-visible{outline:none;box-shadow:0 0 0 3px rgba(79,70,229,.35);}",
      "." +
        classPrefix +
        " button[disabled]{opacity:.75;cursor:not-allowed;transform:none;filter:none;box-shadow:none;}",
      "." + classPrefix + " .stx-arrow{font-size:15px;line-height:1;}",
      "." +
        classPrefix +
        " .stx-captcha{margin-top:11px;padding:11px;border-radius:12px;border:1px solid rgba(79,70,229,.3);background:rgba(79,70,229,.08);}",
      "." +
        classPrefix +
        " .stx-captcha-title{margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-captcha-copy{margin:0 0 8px;font-size:12px;line-height:1.4;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-captcha-solved{margin-top:11px;padding:9px 11px;border-radius:10px;background:rgba(16,185,129,.16);border:1px solid rgba(52,211,153,.32);font-size:12px;font-weight:600;line-height:1.35;color:#a7f3d0;}",
      "." +
        classPrefix +
        " .stx-help{margin-top:10px;font-size:11px;line-height:1.35;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-footnote{margin-top:8px;padding-top:10px;border-top:1px solid rgba(63,63,70,.7);font-size:11px;line-height:1.4;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-status{margin-top:10px;padding:9px 11px;border-radius:10px;background:" +
        palette.statusBg +
        ";border:1px solid rgba(79,70,229,.25);font-size:12px;font-weight:600;line-height:1.35;color:" +
        palette.statusText +
        ";}",
      "." +
        classPrefix +
        " .stx-error{margin-top:10px;padding:9px 11px;border-radius:10px;background:" +
        palette.errorBg +
        ";border:1px solid rgba(248,113,113,.3);font-size:12px;font-weight:600;line-height:1.35;color:" +
        palette.errorText +
        ";}",
      "." + classPrefix + " .stx-scores{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;}",
      "." +
        classPrefix +
        " .stx-score{display:inline-flex;align-items:center;justify-content:center;padding:8px 11px;border-radius:999px;background:" +
        palette.scoreBg +
        ";border:1px solid " +
        palette.scoreBorder +
        ";font-size:11px;font-weight:800;letter-spacing:.06em;color:" +
        palette.scoreText +
        ";}",
      "." +
        classPrefix +
        " .stx-overall{display:inline-flex;align-items:center;margin-top:12px;padding:8px 12px;border-radius:999px;background:rgba(79,70,229,.14);border:1px solid rgba(79,70,229,.34);font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#c7d2fe;}",
      "." +
        classPrefix +
        " .stx-result-note{margin-top:12px;font-size:12px;line-height:1.4;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-setup-shell{position:relative;z-index:1;border:1px solid rgba(79,70,229,.34);border-radius:14px;padding:16px;background:rgba(10,15,32,.55);}",
      "." +
        classPrefix +
        " .stx-setup-title{margin:0;font-size:20px;line-height:1.1;font-weight:800;letter-spacing:-.01em;color:#f8fafc;}",
      "." +
        classPrefix +
        " .stx-setup-copy{margin:10px 0 0;font-size:13px;line-height:1.45;color:" +
        palette.mutedText +
        ";}",
      "." +
        classPrefix +
        " .stx-setup-code{margin-top:12px;padding:10px 12px;border-radius:10px;border:1px solid rgba(79,70,229,.22);background:rgba(2,6,23,.6);font-family:ui-monospace,SFMono-Regular,Menlo,Monaco,Consolas,monospace;font-size:12px;color:#c7d2fe;word-break:break-all;}",
      "@media (max-width:560px){." +
        classPrefix +
        "{max-width:100%;padding:18px;border-radius:16px;}." +
        classPrefix +
        " h3{font-size:36px;line-height:1.02;}." +
        classPrefix +
        " p{font-size:14px;}." +
        classPrefix +
        " button{font-size:15px;}}",
    ].join("");
    document.head.appendChild(styles);
  }

  var formState = {
    mode: "website",
    url: "",
    email: "",
    entity: "",
    captchaMode: captchaSiteKey ? "turnstile" : "fallback",
    captchaToken: "",
    fallbackCaptchaA: 0,
    fallbackCaptchaB: 0,
    fallbackCaptchaAnswer: "",
  };

  var requestSequence = 0;
  var captchaScriptPromise = null;

  function html(content) {
    root.innerHTML = content;
  }

  function hasConfiguredApiKey() {
    if (!apiKey) {
      return false;
    }
    if (invalidApiKeyPlaceholders[normalizedApiKey]) {
      return false;
    }
    return normalizedApiKey.indexOf("stx_embed_") === 0;
  }

  function renderMissingKeyOverlay() {
    html(
      "<div class='" +
        classPrefix +
        "'>" +
        "<div class='stx-header'>" +
        "<span class='stx-kicker'>Setup required</span>" +
        "<h3>Widget Not Configured</h3>" +
        "<p>This widget cannot submit audits until a valid embed API key is set.</p>" +
        "</div>" +
        "<div class='stx-setup-shell'>" +
        "<p class='stx-setup-title'>Add your real embed key</p>" +
        "<p class='stx-setup-copy'>Replace the placeholder in your script tag with a generated key from Dashboard > Leads > Embed Key Manager.</p>" +
        "<div class='stx-setup-code'>data-api-key=&quot;stx_embed_...&quot;</div>" +
        "</div>" +
        "</div>"
    );
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function createRequestId() {
    requestSequence += 1;
    return "embed-" + Date.now().toString(36) + "-" + requestSequence.toString(36);
  }

  function activeCaptchaMode() {
    return formState.captchaMode === "turnstile" ? "turnstile" : "fallback";
  }

  function shouldUseTurnstileCaptcha() {
    return activeCaptchaMode() === "turnstile";
  }

  function resetFallbackCaptcha() {
    formState.fallbackCaptchaA = Math.floor(Math.random() * 7) + 2;
    formState.fallbackCaptchaB = Math.floor(Math.random() * 7) + 2;
    formState.fallbackCaptchaAnswer = "";
  }

  function fallbackCaptchaSolved() {
    var parsed = Number(String(formState.fallbackCaptchaAnswer || "").trim());
    if (!Number.isFinite(parsed)) {
      return false;
    }
    return parsed === formState.fallbackCaptchaA + formState.fallbackCaptchaB;
  }

  function ensureTurnstileLoaded() {
    if (!captchaSiteKey) {
      return Promise.resolve(false);
    }

    if (window.turnstile && typeof window.turnstile.render === "function") {
      return Promise.resolve(true);
    }

    if (captchaScriptPromise) {
      return captchaScriptPromise;
    }

    captchaScriptPromise = new Promise(function (resolve) {
      var existingScript = document.getElementById(classPrefix + "-turnstile-script");
      if (existingScript) {
        if (window.turnstile && typeof window.turnstile.render === "function") {
          resolve(true);
          return;
        }
        existingScript.addEventListener("load", function () {
          resolve(!!window.turnstile);
        });
        existingScript.addEventListener("error", function () {
          resolve(false);
        });
        window.setTimeout(function () {
          resolve(!!window.turnstile);
        }, 2200);
        return;
      }

      var scriptTag = document.createElement("script");
      scriptTag.id = classPrefix + "-turnstile-script";
      scriptTag.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      scriptTag.async = true;
      scriptTag.defer = true;
      scriptTag.onload = function () {
        resolve(!!window.turnstile);
      };
      scriptTag.onerror = function () {
        resolve(false);
      };
      document.head.appendChild(scriptTag);
    });

    return captchaScriptPromise;
  }

  function initCaptchaWidget() {
    if (shouldUseTurnstileCaptcha()) {
      var container = root.querySelector("#stx-captcha-turnstile");
      if (!container) {
        return;
      }

      formState.captchaToken = "";
      ensureTurnstileLoaded().then(function (loaded) {
        if (
          !loaded ||
          !container.isConnected ||
          !window.turnstile ||
          typeof window.turnstile.render !== "function"
        ) {
          formState.captchaMode = "fallback";
          resetFallbackCaptcha();
          renderForm("Captcha switched to fallback mode.", "", false);
          return;
        }

        try {
          window.turnstile.render(container, {
            sitekey: captchaSiteKey,
            theme: isLightTheme ? "light" : "dark",
            callback: function (token) {
              formState.captchaToken = String(token || "");
            },
            "expired-callback": function () {
              formState.captchaToken = "";
            },
            "error-callback": function () {
              formState.captchaToken = "";
            },
          });
        } catch (_error) {
          formState.captchaMode = "fallback";
          resetFallbackCaptcha();
          renderForm("Captcha switched to fallback mode.", "", false);
        }
      });
      return;
    }

    var fallbackInput = root.querySelector("#stx-captcha-answer");
    if (fallbackInput) {
      fallbackInput.addEventListener("input", function () {
        formState.fallbackCaptchaAnswer = fallbackInput.value || "";
      });
    }
  }

  function renderForm(status, error, busy) {
    var isBusy = !!busy;
    var isBrandMode = formState.mode === "brand";

    if (!shouldUseTurnstileCaptcha() && formState.fallbackCaptchaA <= 0) {
      resetFallbackCaptcha();
    }

    var safeStatus = escapeHtml(status || "");
    var safeError = escapeHtml(error || "");
    var safeUrl = escapeHtml(formState.url);
    var safeEmail = escapeHtml(formState.email);
    var safeEntity = escapeHtml(formState.entity);
    var safeButtonText = escapeHtml(isBusy ? "Processing..." : buttonText);
    var disabledAttr = isBusy ? " disabled='disabled'" : "";
    var websiteSelectedAttr = isBrandMode ? "" : " selected='selected'";
    var brandSelectedAttr = isBrandMode ? " selected='selected'" : "";
    var entityRequiredAttr = isBrandMode ? " required" : "";
    var urlOptionalMarkup = isBrandMode
      ? " <span class='stx-field-optional'>(optional)</span>"
      : "";

    html(
      "<div class='" +
        classPrefix +
        "'>" +
        "<div class='stx-header'>" +
        "<span class='stx-kicker'>Instant snapshot</span>" +
        "<h3>Free SEO/GEO/AEO Snapshot</h3>" +
        "<p>Drop in your URL and email to get benchmark scores plus an actionable AI baseline.</p>" +
        "</div>" +
        "<div class='stx-field'>" +
        "<label for='stx-mode'>Assessment Target</label>" +
        "<select id='stx-mode'" +
        disabledAttr +
        ">" +
        "<option value='website'" +
        websiteSelectedAttr +
        ">Website</option>" +
        "<option value='brand'" +
        brandSelectedAttr +
        ">Brand</option>" +
        "</select>" +
        "</div>" +
        "<div class='stx-field'>" +
        "<label for='stx-url'>Website URL" +
        urlOptionalMarkup +
        "</label>" +
        "<input id='stx-url' type='url' inputmode='url' autocomplete='url' placeholder='https://example.com' value='" +
        safeUrl +
        "'" +
        disabledAttr +
        " />" +
        "</div>" +
        "<div class='stx-field'>" +
        "<label for='stx-email'>Email</label>" +
        "<input id='stx-email' type='email' inputmode='email' autocomplete='email' placeholder='you@company.com' value='" +
        safeEmail +
        "' required" +
        disabledAttr +
        " />" +
        "</div>" +
        "<div class='stx-field'>" +
        "<label for='stx-entity'>" +
        (isBrandMode ? "Brand or Entity Name" : "Entity") +
        (isBrandMode ? "" : " <span class='stx-field-optional'>(optional)</span>") +
        "</label>" +
        "<input id='stx-entity' type='text' autocomplete='organization' placeholder='" +
        (isBrandMode ? "Acme Logistics" : "Brand or service") +
        "' value='" +
        safeEntity +
        "'" +
        entityRequiredAttr +
        disabledAttr +
        " />" +
        "</div>" +
        (isBusy
          ? "<div class='stx-captcha-solved'>Captcha verified. Processing your request...</div>"
          : shouldUseTurnstileCaptcha()
            ? "<div class='stx-captcha'><p class='stx-captcha-title'>Captcha Verification</p><p class='stx-captcha-copy'>Complete the security check before submitting.</p><div id='stx-captcha-turnstile'></div></div>"
            : "<div class='stx-captcha'><p class='stx-captcha-title'>Captcha Verification</p><p class='stx-captcha-copy'>Human check: what is " +
              formState.fallbackCaptchaA +
              " + " +
              formState.fallbackCaptchaB +
              "?</p><input id='stx-captcha-answer' type='text' inputmode='numeric' placeholder='Enter answer' value='" +
              escapeHtml(formState.fallbackCaptchaAnswer) +
              "'" +
              disabledAttr +
              " /></div>") +
        "<button id='stx-submit' type='button'" +
        disabledAttr +
        ">" +
        "<span>" +
        safeButtonText +
        "</span>" +
        "<span class='stx-arrow' aria-hidden='true'>&rarr;</span>" +
        "</button>" +
        "<div class='stx-help'>No credit card needed. Your report will be delivered to your inbox.</div>" +
        "<div class='stx-footnote'>Disclaimer: Benchmark scores are indicative and may vary by provider output, location, and crawl accessibility. By submitting this form, you agree to receive audit-related communications.</div>" +
        (safeStatus ? "<div class='stx-status' aria-live='polite'>" + safeStatus + "</div>" : "") +
        (safeError ? "<div class='stx-error' aria-live='polite'>" + safeError + "</div>" : "") +
        "</div>"
    );

    var modeInput = root.querySelector("#stx-mode");
    if (modeInput) {
      modeInput.addEventListener("change", function () {
        formState.mode = modeInput.value === "brand" ? "brand" : "website";
        renderForm("", "", false);
      });
    }

    var urlInput = root.querySelector("#stx-url");
    if (urlInput) {
      urlInput.addEventListener("input", function () {
        formState.url = urlInput.value || "";
      });
    }

    var emailInput = root.querySelector("#stx-email");
    if (emailInput) {
      emailInput.addEventListener("input", function () {
        formState.email = emailInput.value || "";
      });
    }

    var entityInput = root.querySelector("#stx-entity");
    if (entityInput) {
      entityInput.addEventListener("input", function () {
        formState.entity = entityInput.value || "";
      });
    }

    var submitButton = root.querySelector("#stx-submit");
    if (submitButton) {
      submitButton.addEventListener("click", function () {
        void submitLead();
      });
    }

    if (!isBusy) {
      initCaptchaWidget();
    }
  }

  function renderScores(scores) {
    var scoreRows = [
      ["GEO", scores.geo],
      ["SEO", scores.seo],
      ["AEO", scores.aeo],
    ];
    var numericScores = scoreRows
      .map(function (entry) {
        return entry[1];
      })
      .filter(function (value) {
        return typeof value === "number";
      });
    var overallScore = numericScores.length
      ? Math.round(
          numericScores.reduce(function (sum, value) {
            return sum + value;
          }, 0) / numericScores.length
        )
      : null;
    var chips = scoreRows
      .map(function (entry) {
        var value = typeof entry[1] === "number" ? Math.round(entry[1]) : "--";
        return "<span class='stx-score'>" + entry[0] + ": " + value + "</span>";
      })
      .join("");

    html(
      "<div class='" +
        classPrefix +
        "'>" +
        "<div class='stx-header'>" +
        "<span class='stx-kicker'>Snapshot ready</span>" +
        "<h3>Your Audit Scores</h3>" +
        "<p>Your baseline is ready. Use these numbers to prioritize what to fix first.</p>" +
        "</div>" +
        "<div class='stx-scores'>" +
        chips +
        "</div>" +
        (overallScore === null
          ? ""
          : "<div class='stx-overall'>Overall score: " + overallScore + "</div>") +
        "<p class='stx-result-note'>We are preparing the detailed recommendations and sending them by email.</p>" +
        "</div>"
    );
  }

  function request(path, options) {
    var requestOptions = options || {};
    var headers = requestOptions.headers || {};
    if (!headers["X-Request-ID"]) {
      headers["X-Request-ID"] = createRequestId();
    }
    requestOptions.headers = headers;
    return fetch(apiBase + path, requestOptions);
  }

  function submitLead() {
    var modeInput = root.querySelector("#stx-mode");
    var urlInput = root.querySelector("#stx-url");
    var emailInput = root.querySelector("#stx-email");
    var entityInput = root.querySelector("#stx-entity");

    var mode = modeInput && modeInput.value === "brand" ? "brand" : "website";
    var url = (urlInput && urlInput.value ? urlInput.value : "").trim();
    var email = (emailInput && emailInput.value ? emailInput.value : "").trim();
    var entity = (entityInput && entityInput.value ? entityInput.value : "").trim();

    formState.mode = mode;
    formState.url = url;
    formState.email = email;
    formState.entity = entity;

    if (!email) {
      renderForm("", "Email is required.", false);
      return Promise.resolve();
    }

    if (mode === "website" && !url) {
      renderForm("", "Website URL is required for website assessments.", false);
      return Promise.resolve();
    }

    if (mode === "brand" && !entity) {
      renderForm("", "Brand or entity name is required for brand assessments.", false);
      return Promise.resolve();
    }

    if (shouldUseTurnstileCaptcha()) {
      if (!formState.captchaToken) {
        renderForm("", "Please complete captcha verification before submitting.", false);
        return Promise.resolve();
      }
    } else if (!fallbackCaptchaSolved()) {
      renderForm("", "Please solve the captcha challenge before submitting.", false);
      return Promise.resolve();
    }

    renderForm("Submitting your request...", "", true);

    var requestBody = {
      audit_target_type: mode,
      url: url || null,
      email: email,
      entity: entity || null,
      target_name: mode === "brand" ? entity || null : null,
      captcha_token: shouldUseTurnstileCaptcha() ? formState.captchaToken || null : null,
    };

    return request("/api/v1/embed/audit", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Embed-Key": apiKey,
      },
      body: JSON.stringify(requestBody),
    })
      .then(function (response) {
        if (!response.ok) {
          return response
            .json()
            .catch(function () {
              return { detail: "Unable to submit audit." };
            })
            .then(function (payload) {
              throw new Error(
                payload && payload.detail ? payload.detail : "Unable to submit audit."
              );
            });
        }
        return response.json();
      })
      .then(function (payload) {
        renderForm("Audit queued. Gathering results...", "", true);
        return pollStatus(payload.job_id, 0);
      })
      .catch(function (error) {
        if (!shouldUseTurnstileCaptcha()) {
          resetFallbackCaptcha();
        }
        formState.captchaToken = "";
        renderForm("", error && error.message ? error.message : "Submission failed.", false);
      });
  }

  function pollStatus(jobId, attempt) {
    if (!jobId || attempt > 120) {
      formState.captchaToken = "";
      if (!shouldUseTurnstileCaptcha()) {
        resetFallbackCaptcha();
      }
      renderForm("", "Audit timed out. Please try again.", false);
      return;
    }

    request("/api/v1/embed/audit/" + encodeURIComponent(jobId) + "/status", {
      method: "GET",
      headers: {
        "X-Embed-Key": apiKey,
      },
    })
      .then(function (response) {
        if (!response.ok) {
          return response
            .json()
            .catch(function () {
              return { detail: "Unable to fetch audit status." };
            })
            .then(function (payload) {
              throw new Error(
                payload && payload.detail ? payload.detail : "Unable to fetch audit status."
              );
            });
        }
        return response.json();
      })
      .then(function (payload) {
        if (payload.status === "completed" && payload.scores) {
          renderScores(payload.scores);
          return;
        }
        if (payload.status === "failed") {
          formState.captchaToken = "";
          if (!shouldUseTurnstileCaptcha()) {
            resetFallbackCaptcha();
          }
          renderForm("", payload.error || "Audit failed.", false);
          return;
        }
        renderForm("Running audit...", "", true);
        window.setTimeout(function () {
          pollStatus(jobId, attempt + 1);
        }, 3000);
      })
      .catch(function (error) {
        formState.captchaToken = "";
        if (!shouldUseTurnstileCaptcha()) {
          resetFallbackCaptcha();
        }
        renderForm("", error && error.message ? error.message : "Unable to poll status.", false);
      });
  }

  if (!hasConfiguredApiKey()) {
    // eslint-disable-next-line no-console
    console.error("qiko-signal widget: missing or placeholder data-api-key");
    renderMissingKeyOverlay();
    return;
  }

  renderForm("", "", false);
})();
