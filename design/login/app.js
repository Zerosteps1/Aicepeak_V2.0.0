// Aicepeak · Anmelden (interaktiv)
// The whole UI state lives in three data attributes on #app; styles.css animates everything from them.
//   data-theme      light | dark
//   data-phase      out → auth → in
//   data-assistant  closed | open

(() => {
  'use strict';

  // ---- Settings ----
  const CONFIG = {
    authDelayMs: 650, // how long "Anmeldung läuft …" shows before the app opens
    zoom: 0.83,       // app scale behind the sign-in card (0.8–1)
    blurPx: 16,       // app blur behind the sign-in card (0–40)
    labels: {
      idle: 'Mit Microsoft anmelden',
      busy: 'Anmeldung läuft …'
    }
  };

  const app = document.getElementById('app');
  const appLayer = document.getElementById('app-layer');
  const signinLayer = document.getElementById('signin-layer');
  const signinForm = document.getElementById('signin-form');
  const signinLabel = document.getElementById('signin-label');
  const assistantToggle = app.querySelector('[data-action="toggle-assistant"]');
  const assistantBody = document.getElementById('as-body');
  const composer = document.getElementById('composer');

  app.style.setProperty('--app-zoom', String(CONFIG.zoom));
  app.style.setProperty('--app-blur', CONFIG.blurPx + 'px');

  // ---- Theme: ?theme=light|dark, otherwise the system setting ----
  function initialTheme() {
    const param = new URLSearchParams(location.search).get('theme');
    if (param === 'light' || param === 'dark') return param;
    return window.matchMedia && matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }

  function setTheme(theme) {
    app.dataset.theme = theme;
  }

  // ---- Sign-in ----
  let authTimer = null;

  function setPhase(phase) {
    app.dataset.phase = phase;
    const signedIn = phase === 'in';
    signinLabel.textContent = phase === 'auth' ? CONFIG.labels.busy : CONFIG.labels.idle;
    appLayer.setAttribute('aria-hidden', signedIn ? 'false' : 'true');
    appLayer.inert = !signedIn;   // no tabbing into the blurred app while signed out
    signinLayer.inert = signedIn;
  }

  function signIn() {
    if (app.dataset.phase !== 'out') return;
    setPhase('auth');
    authTimer = setTimeout(() => setPhase('in'), CONFIG.authDelayMs);
  }

  function signOut() {
    clearTimeout(authTimer);
    setAssistant(false);
    setPhase('out');
  }

  // ---- Assistant ----
  function setAssistant(open) {
    app.dataset.assistant = open ? 'open' : 'closed';
    assistantToggle.setAttribute('aria-expanded', String(open));
    assistantBody.setAttribute('aria-hidden', String(!open));
    assistantBody.inert = !open;
  }

  function toggleAssistant() {
    if (app.dataset.phase !== 'in') return;
    setAssistant(app.dataset.assistant !== 'open');
  }

  // ---- Wiring ----
  signinForm.addEventListener('submit', (e) => {
    e.preventDefault();
    signIn();
  });

  composer.addEventListener('submit', (e) => {
    e.preventDefault(); // prototype: messages are not sent anywhere
  });

  app.addEventListener('click', (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) return;
    if (target.dataset.action === 'sign-out') signOut();
    if (target.dataset.action === 'toggle-assistant') toggleAssistant();
  });

  // Prototype links go nowhere
  app.addEventListener('click', (e) => {
    const link = e.target.closest('a[href="#"]');
    if (link) e.preventDefault();
  });

  setTheme(initialTheme());
  setPhase('out');
  setAssistant(false);

  // Handy in the browser console: AicepeakLogin.setTheme('light')
  window.AicepeakLogin = { signIn, signOut, toggleAssistant, setTheme, setAssistant };
})();
