# Runtime setup and verification scope

Install resources only through the explicit external setup in the toolkit installation guide. The starter uses Three.js 0.185.0, GSAP 3.15.0, licensed Inter 400/700 fonts and an explicitly configured browser/Node/Puppeteer entry. The source checkout contains no runtime library/font/browser assets.

A stage directory belongs to the configured external workspace. Only that site is served on loopback during tests; never serve a private repository root. Browser requests to remote origins are rejected. Required profile prerequisites must fail visibly when absent, not silently skip.

Choose capture mode explicitly. Prior source diagnostics showed a short hardware repeat mismatch while a short software comparison matched; these are historical diagnostics, not fresh public-profile certification. A supported release profile must separately prove full-size appearance/features, decode, independent decoded repeats and measured cost. Keep hardware failures in evidence even if a verified software path succeeds.

No GUI preview is left running by tests. Python/Node/browser children suppress Windows consoles; owned servers close in finally, browsers close in finally and subprocess timeouts retain logs. No sign-in worker, timed watcher or automatic publish is installed. See the release verification matrix for actual current tested results, not inferred performance.
