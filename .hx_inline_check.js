


/* ═══════════════════════════════════════════════
   CONFIG
═══════════════════════════════════════════════ */
const API = window.location.origin;

/* ═══════════════════════════════════════════════
   GLOBAL STATE
═══════════════════════════════════════════════ */
let _currentUser = null;
let _isAdmin = false;
let _exercisePool = [];
let _muscleGroups = [];
// “Bacak” seans türüdür; kayıt ekranında bağımsız kas olarak gösterilmez.
const DEFAULT_UI_MUSCLE_GROUPS = Object.freeze([
  'Göğüs', 'Sırt', 'Omuz', 'Biceps', 'Triceps',
  'Quadriceps', 'Hamstring', 'Gluteus', 'Calf', 'Adductors', 'Rotatorlar', 'Core'
]);
// Alt vücut filtreleri egzersizin primary_muscles meta verisinden okunur.
const LEG_DETAIL_FILTERS = Object.freeze({
  'Quadriceps': 'quads',
  'Hamstring': 'hamstrings',
  'Gluteus': 'glutes',
  'Calf': 'calves',
  'Adductors': 'adductors'
});
let _selectedExercises = [];
// Geçmişten açılan taslak yalnızca tarayıcı belleğinde tutulur. Bu değer doluyken
// Kaydet, yeni kayıt oluşturmak yerine aynı workout kimliğine PUT gönderir.
let _editingWorkoutId = null;
let _volumeChart = null;
let _muscleChart = null;
let _weeklyAvgChart = null;

/* ═══════════════════════════════════════════════
   SPA NAVIGATION ENGINE
═══════════════════════════════════════════════ */

// ── Sayfa başlıkları ──
const _pageTitles = {
  'dashboard': 'Dashboard',
  'workout': 'Antrenman Kaydı',
  'history': 'Geçmiş',
  'analyze': 'Uzman Sistemi',
  'progress': 'İlerleme',
  'nutrition': 'Beslenme',
  'profile': 'Profil',
  'admin': 'Admin Paneli',
  'custom-program': 'Özel Programım'
};

// ── URL'den sayfa adını al ──
function _currentPageName() {
  const p = window.location.pathname.replace(/^\//, '');
  if (_pageTitles[p] !== undefined) return p;
  return 'dashboard';
}

// ── Geri/İleri butonu yakalayıcı ──
window.addEventListener('popstate', function() {
  if (!_currentUser) return;

  const target = _currentPageName();
  console.log('[NAV] popstate hedef:', target, '| history uzunluğu:', history.length);

  // Dashboard'da geri tuşuna basıldıysa → geri akışı durdur
  // history.forward() kullanıcının login ekranına düşmesini engeller
  if (target === 'dashboard') {
    console.log('[NAV] dashboard\'da geri akışı engellendi');
    history.forward();
    navigate('dashboard');
    return;
  }

  // Hedef sayfayı YÜKLE — pushState YAZMA (tarayıcı kendi kaydında)
  navigate(target);
});

/* ═══════════════════════════════════════════════
   AUTH FUNCTIONS
═══════════════════════════════════════════════ */
function showLogin() {
  document.getElementById('loginPage').classList.remove('hidden');
  document.getElementById('registerPage').classList.add('hidden');
  document.getElementById('appLayout').classList.add('hidden');
  window.history.replaceState(null, '', '/');
  document.title = 'Hypertrophy-X — Giriş';
}
function showRegister() {
  document.getElementById('loginPage').classList.add('hidden');
  document.getElementById('registerPage').classList.remove('hidden');
  document.title = 'Hypertrophy-X — Hesap Oluştur';
}
function hideAllAuth() {
  document.getElementById('loginPage').classList.add('hidden');
  document.getElementById('registerPage').classList.add('hidden');
}

async function doLogin() {
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl = document.getElementById('loginError');
  errEl.classList.remove('show');

  if (!username || !password) { errEl.textContent = 'Kullanıcı adı ve şifre gerekli'; errEl.classList.add('show'); return; }

  try {
    const res = await fetch(`${API}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    if (!res.ok) {
      const d = await res.json();
      errEl.textContent = d.detail || 'Giriş başarısız';
      errEl.classList.add('show');
      return;
    }
    const data = await res.json();

    // Token'ı sakla (JWT — güvenlik katmanı)
    _isAdmin = !!data.is_admin;

    if (_isAdmin) {
      _currentUser = { username: data.username, is_admin: true };
    } else {
      _currentUser = data;
    }
    localStorage.setItem('hx_token', data.token);
    localStorage.setItem('hx_user', _currentUser.username);
    localStorage.setItem('hx_loggedIn', 'true');
    localStorage.setItem('hx_pass', password);
    localStorage.setItem('hx_isAdmin', _isAdmin ? '1' : '0');
    enterApp();
  } catch (e) {
    errEl.textContent = 'Bağlantı hatası: ' + e.message;
    errEl.classList.add('show');
  }
}

async function doRegister() {
  const username = document.getElementById('regUsername').value.trim();
  const password = document.getElementById('regPassword').value;
  const confirm = document.getElementById('regPasswordConfirm').value;
  const errEl = document.getElementById('registerError');
  errEl.classList.remove('show');

  if (!username || !password) { errEl.textContent = 'Tüm alanları doldurun'; errEl.classList.add('show'); return; }
  if (password !== confirm) { errEl.textContent = 'Şifreler eşleşmiyor'; errEl.classList.add('show'); return; }
  if (password.length < 3) { errEl.textContent = 'Şifre en az 3 karakter olmalı'; errEl.classList.add('show'); return; }

  try {
    const res = await fetch(`${API}/api/auth/register`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username, password})
    });
    if (!res.ok) {
      const d = await res.json();
      errEl.textContent = d.detail || 'Kayıt başarısız';
      errEl.classList.add('show');
      return;
    }
    toast('Hesap oluşturuldu! Giriş yapabilirsiniz.', 'success');
    showLogin();
  } catch(e) {
    errEl.textContent = 'Bağlantı hatası: ' + e.message;
    errEl.classList.add('show');
  }
}

function doLogout() {
  localStorage.removeItem('hx_user');
  localStorage.removeItem('hx_loggedIn');
  localStorage.removeItem('hx_isAdmin');
  localStorage.removeItem('hx_token');
  localStorage.removeItem('hx_pass');
  _currentUser = null;
  _isAdmin = false;
  showLogin();
  closeDropdown();
}

/* ═══════════════════════════════════════════════
   ENTER APP
══════════════════════════════════════════════════ */
function enterApp() {
  hideAllAuth();
  document.getElementById('appLayout').classList.remove('hidden');

  // Update topbar
  const name = _currentUser.username || _currentUser.username;
  document.getElementById('userDropdownName').textContent = name;
  document.getElementById('ddName').textContent = name;
  document.getElementById('ddRole').textContent = _isAdmin ? 'Admin' : 'Kullanıcı';
  document.getElementById('userAvatar').textContent = name.charAt(0).toUpperCase();

  // Build sidebar
  buildSidebar();

  // '/' kaydını '/dashboard'a dönüştür ve dashboard'ı yükle
  window.history.replaceState({ page: 'dashboard' }, '', '/dashboard');
  document.title = 'Dashboard — Hypertrophy-X';
  navigate('dashboard');
}

/* ═══════════════════════════════════════════════
   SIDEBAR BUILDER
═══════════════════════════════════════════════ */
function buildSidebar() {
  const nav = document.getElementById('sidebarNav');
  let html = '';

  if (_isAdmin) {
    // Admin-only menu
    html += `
      <div class="nav-section-title">Yönetim</div>
      <div class="nav-item active" data-page="admin" onclick="navigate('admin',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-2.573 1.066c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-1.066 2.573c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0 3.35a1.724 1.724 0 001.066 2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 116 0z"/></svg>
        <span>Admin Paneli</span>
      </div>
    `;
  } else {
    // Normal user menu
    html += `
      <div class="nav-section-title">Menü</div>
      <div class="nav-item active" data-page="dashboard" onclick="navigate('dashboard',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zm10 0a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"/></svg>
        <span>Dashboard</span>
      </div>
      <div class="nav-item" data-page="workout" onclick="navigate('workout',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/></svg>
        <span>Antrenman Kaydı</span>
      </div>
      <div class="nav-item" data-page="history" onclick="navigate('history',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
        <span>Geçmiş</span>
      </div>
      <div class="nav-item" data-page="custom-program" onclick="navigate('custom-program', this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:18px;height:18px;">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
        </svg>
        <span>Özel Programım</span>
      </div>


      <div class="nav-section-title">ANALİZ</div>
      <div class="nav-item" data-page="analyze" onclick="navigate('analyze',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 10-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
        <span>Uzman Sistemi</span>
      </div>
      <div class="nav-item" data-page="progress" onclick="navigate('progress',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>
        <span>İlerleme</span>
      </div>
      <div class="nav-item" data-page="nutrition" onclick="navigate('nutrition',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"/></svg>
        <span>Beslenme</span>
      </div>

      <div class="nav-section-title">KİŞİSEL</div>
      <div class="nav-item" data-page="profile" onclick="navigate('profile',this)">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 118 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
        <span>Profil</span>
      </div>
    `;
  }

  nav.innerHTML = html;
}

/* ═══════════════════════════════════════════════
   NAVIGATION
═══════════════════════════════════════════════ */
async function navigate(page, el) {
  console.log('[NAV] navigate:', page);

  // Update active nav
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (el) el.classList.add('active');
  else {
    const target = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (target) target.classList.add('active');
  }

  // Show page — page div'ini görünür yap
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  const pageEl = document.getElementById(`page-${page}`);
  if (pageEl) {
    pageEl.classList.add('active');
  } else {
    console.error('[NAV] page div bulunamadı: page-' + page);
    toast('Sayfa bulunamadı: ' + page, 'error');
    return;
  }

  // Close mobile sidebar after selecting a page
  closeMobileSidebar();

  // URL'yi güncelle (her zaman — menüden ve popstate'ten de)
  // popstate'te tarayıcı URL'yi zaten değiştirdi; burada yazdığımız
  // kayıt AYNI URL'yi yazar ve hiçbir şeyi bozmaz.
  window.history.pushState({ page: page }, '', '/' + page);
  document.title = (_pageTitles[page] || 'Hypertrophy-X') + ' — Hypertrophy-X';

  // Load page data
  const uname = _currentUser?.username;
  try {
    if (page === 'dashboard') await loadDashboard(uname);
    else if (page === 'workout') await loadWorkoutPage();
    else if (page === 'history') await loadHistory(uname);
    else if (page === 'analyze') { setTimeout(() => onAnalyzePageEnter(), 120); }
    else if (page === 'progress') await loadProgress(uname);
    else if (page === 'nutrition') await loadNutrition(uname);
    else if (page === 'custom-program') await loadCustomProgram(uname);
    else if (page === 'profile') await loadProfile(uname);
    else if (page === 'admin') await loadAdminPanel();
  } catch(e) {
    console.error('[NAV] Sayfa yük hatası:', e);
    toast('Sayfa yüklenirken hata: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════
   SIDEBAR TOGGLE
═══════════════════════════════════════════════ */
function isMobileViewport() {
  return window.matchMedia('(max-width: 768px)').matches;
}

function closeMobileSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('mobileMenuBackdrop');
  const toggle = document.querySelector('.hamburger-btn');
  if (!sidebar || !backdrop) return;

  sidebar.classList.remove('mobile-open');
  backdrop.classList.remove('show');
  document.body.classList.remove('mobile-menu-open');
  if (toggle) toggle.setAttribute('aria-expanded', 'false');
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('mobileMenuBackdrop');
  const toggle = document.querySelector('.hamburger-btn');
  if (!sidebar) return;

  if (isMobileViewport()) {
    const isOpen = sidebar.classList.toggle('mobile-open');
    sidebar.classList.remove('collapsed');
    if (backdrop) backdrop.classList.toggle('show', isOpen);
    document.body.classList.toggle('mobile-menu-open', isOpen);
    if (toggle) toggle.setAttribute('aria-expanded', String(isOpen));
    return;
  }

  closeMobileSidebar();
  sidebar.classList.toggle('collapsed');
}

window.addEventListener('resize', () => {
  if (!isMobileViewport()) closeMobileSidebar();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && isMobileViewport()) closeMobileSidebar();
});

/* ═══════════════════════════════════════════════
   THEME
═══════════════════════════════════════════════ */
function toggleTheme() {
  const isLight = document.body.classList.toggle('light-mode');
  localStorage.setItem('hx_theme', isLight ? 'light' : 'dark');
  updateThemeIcon();
}
function loadTheme() {
  const theme = localStorage.getItem('hx_theme');
  if (theme === 'light') {
    document.body.classList.add('light-mode');
  }
  updateThemeIcon();
}
function updateThemeIcon() {
  const icon = document.getElementById('themeIcon');
  const isLight = document.body.classList.contains('light-mode');
  icon.innerHTML = isLight
    ? '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21.752 15.002A9.718 9.718 0 0118 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 003 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 009.002-5.998z"/>'
    : '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 118 0z"/>';
}

/* ═══════════════════════════════════════════════
   DROPDOWN
═══════════════════════════════════════════════ */
function toggleDropdown() { document.getElementById('userDropdown').classList.toggle('show'); }
function closeDropdown() { document.getElementById('userDropdown').classList.remove('show'); }
document.addEventListener('click', (e) => {
  if (!e.target.closest('.user-dropdown')) closeDropdown();
});

/* ═══════════════════════════════════════════════
   API HELPERS (JWT ZIRHLI)
═══════════════════════════════════════════════ */
function hxAuthHeaders() {
  const token = localStorage.getItem('hx_token');
  return {
    'Content-Type': 'application/json',
    'Authorization': token ? `Bearer ${token}` : ''
  };
}
async function apiGet(url) {
  const res = await fetch(`${API}${url}`, { headers: hxAuthHeaders() });
  if (res.status === 401) { doLogout(); throw new Error('Oturum süresi doldu, lütfen tekrar giriş yapın.'); }
  if (!res.ok) { const d = await res.json().catch(()=>({})); throw new Error(d.detail || `HTTP ${res.status}`); }
  return await res.json();
}
async function apiPost(url, data) {
  const res = await fetch(`${API}${url}`, { method:'POST', headers: hxAuthHeaders(), body: JSON.stringify(data) });
  if (res.status === 401) { doLogout(); throw new Error('Oturum süresi doldu, lütfen tekrar giriş yapın.'); }
  if (!res.ok) { const d = await res.json().catch(()=>({})); throw new Error(d.detail || `HTTP ${res.status}`); }
  return await res.json();
}
async function apiDelete(url) {
  const res = await fetch(`${API}${url}`, { method:'DELETE', headers: hxAuthHeaders() });
  if (res.status === 401) { doLogout(); throw new Error('Oturum süresi doldu, lütfen tekrar giriş yapın.'); }
  if (!res.ok) { const d = await res.json().catch(()=>({})); throw new Error(d.detail || `HTTP ${res.status}`); }
  return await res.json();
}
async function apiPut(url, data) {
  const res = await fetch(`${API}${url}`, { method:'PUT', headers: hxAuthHeaders(), body: JSON.stringify(data) });
  if (res.status === 401) { doLogout(); throw new Error('Oturum süresi doldu, lütfen tekrar giriş yapın.'); }
  if (!res.ok) { const d = await res.json().catch(()=>({})); throw new Error(d.detail || `HTTP ${res.status}`); }
  return await res.json();
}

function normalizeCustomSplitJson(rawSplit) {
  try {
    const parsed = typeof rawSplit === 'string' ? JSON.parse(rawSplit || '[]') : rawSplit;
    return Array.isArray(parsed) ? JSON.stringify(parsed) : '[]';
  } catch (_) {
    return '[]';
  }
}

function getServerPRTargets() {
  const targets = cachedUserData?.dashboard_preferences?.pr_targets;
  return targets && typeof targets === 'object' ? targets : {};
}

function applyDashboardPreferences(preferences) {
  if (!cachedUserData) return;
  cachedUserData.dashboard_preferences = preferences && typeof preferences === 'object'
    ? preferences
    : { schema_version: 1, pr_targets: {} };
}

/* ═══════════════════════════════════════════════
   TOAST
═══════════════════════════════════════════════ */
function toast(msg, type='info') {
  const c = document.getElementById('toastContainer');
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}


/* ═══════════════════════════════════════════════
   DASHBOARD ANA FONKSİYONU
═══════════════════════════════════════════════ */

let cachedUserData = null;
// Sunucudaki son doğrulanmış split; kayıt başarısız olursa güvenli geri alma için tutulur.
let lastConfirmedCustomSplitJson = '[]';
let customSplitSaveQueue = Promise.resolve();
let customSplitSaveVersion = 0;
let expertRecommendationSaveQueue = Promise.resolve();
let expertRecommendationWeekIndex = 0;
let volumeChart = null; // Grafikler için global değişkenler
let muscleChart = null;

function expertRecommendationFromData(data = cachedUserData) {
  const value = data?.dashboard_preferences?.expert_recommendation;
  return value && typeof value === 'object' && Array.isArray(value.weeks) ? value : null;
}
function expertRecommendationWeek(recommendation, index = getWeekNum(new Date())) {
  const weeks = recommendation?.weeks || [];
  if (!weeks.length) return { index: 0, days: [] };
  const safeIndex = ((Number(index) || 0) % weeks.length + weeks.length) % weeks.length;
  return { index: safeIndex, days: Array.isArray(weeks[safeIndex]?.days) ? weeks[safeIndex].days : [] };
}
function getDashboardProgramSummary(data, preferredMode = localStorage.getItem('selectedSplitMode') || 'custom') {
  const recommendation = expertRecommendationFromData(data);
  const recommendationWeek = expertRecommendationWeek(recommendation);
  const recommendationSessions = recommendationWeek.days.filter(day => !day?.isRest && !String(day?.type || '').toLowerCase().includes('dinlenme')).length;
  let customWeek = [];
  let customWeekIndex = 0;
  try {
    const rawCustomSplit = data?.user?.custom_split;
    const customProgram = Array.isArray(rawCustomSplit) ? rawCustomSplit : JSON.parse(rawCustomSplit || '[]');
    if (Array.isArray(customProgram) && customProgram.length) {
      customWeekIndex = getWeekNum(new Date()) % customProgram.length;
      customWeek = Array.isArray(customProgram[customWeekIndex]) ? customProgram[customWeekIndex] : [];
    }
  } catch (_) { customWeek = []; }
  const customSessionCount = customWeek.filter(day => !day?.isRest && !String(day?.type || '').toLowerCase().includes('rest') && !String(day?.type || '').toLowerCase().includes('dinlenme')).length;
  const activeExpert = data?.expert_program_summary;
  const activeExpertSessions = Number(activeExpert?.session_count || 0);
  if (preferredMode === 'expert' && recommendation && recommendationSessions) {
    return { name: `${recommendation.name || 'Uzman Önerisi'} · ${recommendationWeek.index + 1}. Hafta`, sessionCount: recommendationSessions, source: 'expert-recommendation' };
  }
  if (customWeek.length && customSessionCount) return { name: `Özel Programım · ${customWeekIndex + 1}. Hafta`, sessionCount: customSessionCount, source: 'custom' };
  if (recommendation && recommendationSessions) return { name: recommendation.name || 'Uzman Önerisi', sessionCount: recommendationSessions, source: 'expert-recommendation' };
  if (activeExpert && activeExpertSessions) return { name: activeExpert.name || 'Uzman Programı', sessionCount: activeExpertSessions, source: 'expert' };
  return { name: 'Program Yok', sessionCount: 0, source: 'none' };
}

function refreshDashboardProgramStat(preferredMode) {
  if (!cachedUserData) return;
  const summary = getDashboardProgramSummary(cachedUserData, preferredMode);
  const title = document.getElementById('dashboardProgramName');
  const detail = document.getElementById('dashboardProgramDetail');
  if (title) title.textContent = summary.name;
  if (detail) detail.textContent = summary.sessionCount ? `${summary.sessionCount} gün bölünmüş program` : 'Henüz aktif bir program yok';
}

async function loadDashboard(username) {
  // 1. Veriyi Çek
  const data = await apiGet(`/api/dashboard`);
  cachedUserData = data;
  lastConfirmedCustomSplitJson = normalizeCustomSplitJson(data.user?.custom_split);
  const s = data.summary || {};
  const dashboardProgram = getDashboardProgramSummary(data);

  // 2. Başlık
  const subtitleEl = document.getElementById('dashSubtitle');
  if (subtitleEl) {
    subtitleEl.textContent = `${new Date().toLocaleDateString('tr-TR', {day:'numeric',month:'long',year:'numeric'})} · ${username}`;
  }

  // 3. Üst İstatistik Kartları
  const dashStatsEl = document.getElementById('dashStats');
  if (dashStatsEl) {
    dashStatsEl.innerHTML = `
      <div class="stat-card accent">
        <div class="stat-icon" style="background:var(--accent-bg);color:var(--accent)">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
        </div>
        <div class="stat-value">${s.weekly || 0}/${s.monthly || 0}/${s.total || 0}</div>
        <div class="stat-label">Haftalık / Aylık / Toplam</div>
        <div class="stat-detail">Seri: ${s.streak || 0} gün · Dinlenme: ${data.rest_days || 0} gün</div>
      </div>
      <div class="stat-card green">
        <div class="stat-icon" style="background:var(--green-bg);color:var(--green)">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>
        </div>
        <div class="stat-value" id="dashboardProgramName" style="font-size:18px">${dashboardProgram.name}</div>
        <div class="stat-label">Antrenman Programı</div>
        <div class="stat-detail" id="dashboardProgramDetail">${dashboardProgram.sessionCount ? `${dashboardProgram.sessionCount} gün bölünmüş program` : 'Henüz aktif bir program yok'}</div>
      </div>
      <div class="stat-card orange">
        <div class="stat-icon" style="background:var(--orange-bg);color:var(--orange)">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3"/></svg>
        </div>
        <div class="stat-value">${data.stats?.bmi || '-'}</div>
        <div class="stat-label">BMI — ${data.stats?.bmi_category || '-'}</div>
        <div class="stat-detail">Kilo: ${data.user?.weight || '-'}kg · Boy: ${data.user?.height || '-'}cm</div>
      </div>
      <div class="stat-card blue">
        <div class="stat-icon" style="background:var(--blue-bg);color:var(--blue)">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 18.657A8 8 0 016.343 7.343S7 9 9 10c0-2 .5-5 2.986-7C14 5 16.09 5.777 17.656 7.343A7.975 7.975 0 0120 13a7.975 7.975 0 01-2.343 5.657z"/></svg>
        </div>
        <div class="stat-value" style="font-size:18px">${data.user?.goal || 'bulk'}</div>
        <div class="stat-label">Hedef: ${data.stats?.target_calories || '-'} kcal</div>
        <div class="stat-detail">Protein: ${data.stats?.macro?.protein || '-'}g · Karb: ${data.stats?.macro?.carbs || '-'}g · Yağ: ${data.stats?.macro?.fat || '-'}g</div>
      </div>
    `;
  }

  if (data.muscle_distribution && data.muscle_distribution.all && document.getElementById('muscleChart')) {
    const musLabels = Object.keys(data.muscle_distribution.all);
    const musValues = Object.values(data.muscle_distribution.all);
    const musDetails = data.muscle_distribution_details?.all || {};
    renderMuscleChart(musLabels, musValues, musDetails);
  }


  // 5. SPLIT PROGRAMI YÜKLEME
  const savedMode = localStorage.getItem('selectedSplitMode') || 'custom';
  switchSplitMode(savedMode);

  // 6. MOTORLARI ÇALIŞTIR
  await loadDashboardPRTable(username);
  await loadDashboardRPG(username);
}

// Butonlara tıklanınca çalışacak grafik filtreleme motoru
window.filterMuscleChart = function(timeframe, btnEl) {
  const parent = btnEl.parentElement;
  if (parent) {
    parent.querySelectorAll('.tf-pill').forEach(button => button.classList.remove('active'));
  }
  btnEl.classList.add('active');

  if (!cachedUserData || !cachedUserData.muscle_distribution) return;
  const distData = cachedUserData.muscle_distribution[timeframe] || {};
  const detailData = cachedUserData.muscle_distribution_details?.[timeframe] || {};

  const musLabels = Object.keys(distData);
  const musValues = Object.values(distData);
  renderMuscleChart(musLabels, musValues, detailData);
};


/* ═══════════════════════════════════════════════
   RPG & XP AKILLI KALİBRASYON MOTORU
═══════════════════════════════════════════════ */
async function loadDashboardRPG(username) {
  const titleEl = document.getElementById('rpgTitle');
  if (!titleEl) return;

  try {
    const REQUIRED_MUSCLES = [
      'Göğüs', 'Sırt', 'Omuz', 'Quadriceps',
      'Hamstring', 'Glute', 'Calf', 'Biceps',
      'Triceps'
    ];

    let workouts = await apiGet(`/api/workouts`);

    if (!workouts || !Array.isArray(workouts)) {
        workouts = [];
    }

    workouts.sort((a, b) => new Date(a.date) - new Date(b.date));

    const completedMusclesSet = new Set();
    const baselines = {};
    const COMPOUND_KEYWORDS = ['bench', 'squat', 'deadlift', 'overhead', 'row', 'dip', 'bulgarian'];
    // Yeni hareket havuzundaki ayrıntılı ana kas tanımları önce kullanılır.
    // Böylece Legs gibi geniş bir görünür grup, hamstring/glute kaydını gizlemez.
    const PRIMARY_TO_RPG_MUSCLE = {
      chest: 'Göğüs', lats: 'Sırt', upper_back: 'Sırt', traps: 'Sırt',
      rear_delts: 'Omuz', side_delts: 'Omuz', front_delts: 'Omuz',
      quadriceps: 'Quadriceps', hamstrings: 'Hamstring', glutes: 'Glute',
      calves: 'Calf', biceps: 'Biceps', triceps: 'Triceps'
    };
    const normalizeRpgText = value => String(value || '')
      .toLocaleLowerCase('tr-TR')
      .replace(/ı/g, 'i')
      .replace(/ü/g, 'u')
      .replace(/ğ/g, 'g')
      .replace(/ş/g, 's')
      .replace(/ö/g, 'o')
      .replace(/ç/g, 'c');

    let totalXP = 0;

    workouts.forEach(w => {
      let exercises = [];
      try {
        if (typeof w.exercises === 'string') {
            exercises = JSON.parse(w.exercises);
        } else if (Array.isArray(w.exercises)) {
            exercises = w.exercises;
        }
      } catch(e) { console.warn("Antrenman okunamadı:", e); }

      exercises.forEach(ex => {
        const muscle = ex.muscle_group || ex.muscle || "";
        const exName = normalizeRpgText(ex.exercise_name || ex.name || "");
        const sets = ex.sets_data || [];
        const matchedMuscles = new Set();
        const catalogExercise = (_exercisePool || []).find(item =>
          item.id === ex.canonical_exercise_id || item.id === ex.exercise_id ||
          item.name === ex.exercise_name || item.name === ex.name
        );
        const primaryMuscles = ex.analysis?.primary_muscles || ex.primary_muscles ||
          catalogExercise?.analysis?.primary_muscles || [];
        (Array.isArray(primaryMuscles) ? primaryMuscles : []).forEach(primary => {
          const mapped = PRIMARY_TO_RPG_MUSCLE[String(primary || '').toLowerCase()];
          if (mapped) matchedMuscles.add(mapped);
        });

        // Eski kayıtlar ayrıntılı analiz meta verisi içermeyebilir. Bu nedenle
        // hareket ismi ve görünür grup üzerinden geri uyumlu bir eşleştirme kalır.
        const exactGroup = REQUIRED_MUSCLES.find(m => normalizeRpgText(m) === normalizeRpgText(muscle));
        if (exactGroup) matchedMuscles.add(exactGroup);
        if (!matchedMuscles.size) {
          if (exName.includes('hamstring') || exName.includes('leg curl') || exName.includes('romanian') || exName.includes('rdl')) matchedMuscles.add('Hamstring');
          else if (exName.includes('glute') || exName.includes('hip thrust') || exName.includes('kickback') || exName.includes('abduction') || exName.includes('bulgarian')) matchedMuscles.add('Glute');
          else if (exName.includes('calf') || exName.includes('calves')) matchedMuscles.add('Calf');
          else if (exName.includes('squat') || exName.includes('leg press') || exName.includes('leg extension')) matchedMuscles.add('Quadriceps');
          else if (exName.includes('chest') || exName.includes('bench') || exName.includes('fly')) matchedMuscles.add('Göğüs');
          else if (exName.includes('back') || exName.includes('lat') || exName.includes('row') || exName.includes('pulldown')) matchedMuscles.add('Sırt');
          else if (exName.includes('shoulder') || exName.includes('lateral raise') || exName.includes('overhead')) matchedMuscles.add('Omuz');
          else if (exName.includes('triceps') || exName.includes('pushdown')) matchedMuscles.add('Triceps');
          else if (exName.includes('biceps') || exName.includes('curl')) matchedMuscles.add('Biceps');
        }

        let hasValidSet = false;
        sets.forEach(s => {
          const weight = parseFloat(s.weight_kg) || 0;
          const reps = parseFloat(s.reps) || 0;

          if (reps > 0) {
            hasValidSet = true;

            if (weight > 0 && !baselines[exName]) {
              baselines[exName] = weight;
            }

            const isCompound = COMPOUND_KEYWORDS.some(k => exName.includes(k));
            const basePoints = isCompound ? 10 : 5;
            const multiplier = isCompound ? 1.2 : 1.5;

            let pointsForSet = basePoints;
            if (weight > 0 && baselines[exName] > 0 && weight >= (baselines[exName] * 1.05)) {
              pointsForSet = basePoints * multiplier;
            }
            totalXP += pointsForSet;
          }
        });

        if (hasValidSet) {
          matchedMuscles.forEach(muscleName => completedMusclesSet.add(muscleName));
        }
      });
    });

    const completedCount = completedMusclesSet.size;
    const totalRequired = REQUIRED_MUSCLES.length;
    const isCalibrationComplete = completedCount >= totalRequired;

    const badgeEl = document.getElementById('rpgLevelBadge');
    const subtitleEl = document.getElementById('rpgSubtitle');
    const nextTextEl = document.getElementById('rpgNextLevelText');
    const fillEl = document.getElementById('rpgXpFill');
    const currentXpEl = document.getElementById('rpgCurrentXp');
    const targetXpEl = document.getElementById('rpgTargetXp');

    if (!isCalibrationComplete) {
      const missingMuscles = REQUIRED_MUSCLES.filter(m => !completedMusclesSet.has(m));
      const progressPercent = Math.round((completedCount / totalRequired) * 100);

      badgeEl.innerText = `KURULUM %${progressPercent}`;
      badgeEl.className = "badge badge-orange";
      subtitleEl.innerText = "XP Sistemini aktif etmek için tüm kasları çalıştır";

      titleEl.innerText = "KAS GRUBU TAMAMLAMA";
      titleEl.style.fontSize = "18px";

      nextTextEl.innerHTML = `
        <div style="color:var(--orange, #f59e0b); font-weight:700; margin-bottom:4px;">
           XP Sistemi Kilitli!
        </div>
        <div style="font-size:11px; color:var(--text-muted);">
          Henüz verisini girmediğin kaslar: <br>
          <strong style="color:var(--text);">${missingMuscles.join(', ')}</strong>
        </div>
      `;

      currentXpEl.innerText = `${completedCount} / ${totalRequired} Kas Grubu`;
      targetXpEl.innerText = `%${progressPercent} Tamamlandı`;

      setTimeout(() => {
        fillEl.style.width = `${progressPercent}%`;
        fillEl.style.background = "linear-gradient(90deg, #f59e0b, #ef4444)";
      }, 100);

    } else {
      totalXP = Math.round(totalXP);

      const LEVEL_THRESHOLDS = [0, 500, 1000, 5000, 15000, 35000, 75000];
      const TITLES = ["Yok", "Çaylak", "Demir Bükücü", "Çelik İradesi", "Spartalı", "Titan", "Yarı Tanrı", "Olimposlu"];

      let currentLevel = 1;
      let prevTarget = 0;
      let nextTarget = LEVEL_THRESHOLDS[1];

      for (let i = 0; i < LEVEL_THRESHOLDS.length; i++) {
        if (totalXP >= LEVEL_THRESHOLDS[i]) {
          currentLevel = i + 1;
          prevTarget = LEVEL_THRESHOLDS[i];
          nextTarget = LEVEL_THRESHOLDS[i + 1] || LEVEL_THRESHOLDS[i];
        } else {
          break;
        }
      }

      const xpInCurrentLevel = totalXP - prevTarget;
      const levelSize = nextTarget - prevTarget;
      let progressPercent = 100;
      let xpLeft = 0;

      if (levelSize > 0) {
        progressPercent = (xpInCurrentLevel / levelSize) * 100;
        xpLeft = nextTarget - totalXP;
      }

      badgeEl.innerText = `LVL ${currentLevel}`;
      badgeEl.className = "badge badge-accent";
      subtitleEl.innerText = "Ağırlık artırdıkça Bonus XP kazan!";

      titleEl.innerText = TITLES[currentLevel] || "Efsanevi Sporcu";
      titleEl.style.fontSize = "24px";

      if (levelSize > 0) {
        nextTextEl.innerText = `Seviye ${currentLevel + 1}'e ulaşmana ${Math.round(xpLeft)} XP kaldı!`;
      } else {
        nextTextEl.innerText = `Maksimum seviyeye ulaştın!`;
      }

      currentXpEl.innerText = `${Math.round(totalXP)} XP`;
      targetXpEl.innerText = `${nextTarget} XP`;

      setTimeout(() => {
        fillEl.style.width = `${progressPercent}%`;
        fillEl.style.background = "linear-gradient(90deg, #3b82f6, var(--accent), #d946ef)";
      }, 100);
    }
  } catch (err) {
    console.error("RPG Motoru çöktü, sistem durduruldu:", err);
    document.getElementById('rpgNextLevelText').innerHTML = `<span style="color:#ef4444;">Veriler alınırken hata oluştu.</span>`;
  }
}


/* ═══════════════════════════════════════════════
   PR HEDEF VE İLERLEME MOTORU
═══════════════════════════════════════════════ */
const TARGET_COMPOUNDS = [
  { key: 'bench', name: 'Bench Press', icon: '🏋️‍♂️' },
  { key: 'squat', name: 'Squat', icon: '🦵' },
  { key: 'deadlift', name: 'Deadlift', icon: '⚡' },
  { key: 'overhead', name: 'Overhead Press', icon: '🎯' },
  { key: 'row', name: 'Barbell Row', icon: '💪' },
  { key: 'bulgarian', name: 'Bulgarian Split', icon: '🔥' }
];

let globalPRData = {};
let isPREditMode = false;

async function loadDashboardPRTable(username) {
  const container = document.getElementById('prListContainer');
  if (!container) return;

  const workouts = await apiGet(`/api/workouts`);

  TARGET_COMPOUNDS.forEach(ex => { globalPRData[ex.key] = 0; });

  if (workouts && workouts.length > 0) {
    workouts.forEach(w => {
      let exercises = [];
      try { exercises = typeof w.exercises === 'string' ? JSON.parse(w.exercises) : w.exercises || []; } catch(e) {}

      exercises.forEach(ex => {
        const exName = (ex.exercise_name || "").toLowerCase();

        TARGET_COMPOUNDS.forEach(target => {
          let isMatch = false;
          if (target.key === 'bench' && exName.includes('bench press')) isMatch = true;
          if (target.key === 'squat' && exName.includes('squat') && !exName.includes('bulgarian')) isMatch = true;
          if (target.key === 'deadlift' && exName.includes('deadlift')) isMatch = true;
          if (target.key === 'overhead' && (exName.includes('overhead press') || exName.includes('ohp'))) isMatch = true;
          if (target.key === 'row' && exName.includes('barbell row')) isMatch = true;
          if (target.key === 'bulgarian' && exName.includes('bulgarian')) isMatch = true;

          if (isMatch) {
            const sets = ex.sets_data || [];
            sets.forEach(s => {
              const weight = parseFloat(s.weight_kg) || 0;
              if (weight > globalPRData[target.key]) {
                globalPRData[target.key] = weight;
              }
            });
          }
        });
      });
    });
  }

  renderPRList(username);
}

function renderPRList(username) {
  const container = document.getElementById('prListContainer');
  if (!container) return;

  // PR hedefleri cihazdaki localStorage yerine kullanıcı hesabına bağlı olarak gelir.
  const savedTargets = getServerPRTargets();
  let html = '';

  TARGET_COMPOUNDS.forEach(ex => {
    const currentMax = globalPRData[ex.key];
    const target = savedTargets[ex.key] || 0;

    let percentage = 0;
    if (target > 0) {
      percentage = Math.min(100, Math.round((currentMax / target) * 100));
    } else if (currentMax > 0) {
      percentage = 100;
    }

    if (isPREditMode) {
      html += `
        <div class="pr-item">
          <div class="pr-header" style="margin-bottom:0;">
            <div class="pr-title-text">${ex.icon} ${ex.name}</div>
            <div style="display:flex; align-items:center; gap:8px;">
              <span style="font-size:11px; color:var(--text-muted);">Mevcut: ${currentMax}kg</span>
              <span style="font-size:12px; color:var(--text);">Hedef:</span>
              <input type="number" id="pr_input_${ex.key}" class="pr-input" value="${target}">
            </div>
          </div>
        </div>
      `;
    } else {
      const targetText = target > 0 ? target + 'kg' : '<span style="font-size:10px; color:#ef4444;">Hedef Belirle</span>';

      html += `
        <div class="pr-item">
          <div class="pr-header">
            <div class="pr-title-text">${ex.icon} ${ex.name}</div>
            <div class="pr-values"><strong>${currentMax}kg</strong> / ${targetText}</div>
          </div>
          <div class="pr-progress-bg">
            <div class="pr-progress-fill" style="width: 0%;" data-target-width="${percentage}%"></div>
          </div>
          ${target > 0 ? `<div style="text-align:right; font-size:9px; color:var(--accent); margin-top:4px;">%${percentage} Tamamlandı</div>` : ''}
        </div>
      `;
    }
  });

  container.innerHTML = html;

  if (!isPREditMode) {
    setTimeout(() => {
      document.querySelectorAll('.pr-progress-fill').forEach(bar => {
        bar.style.width = bar.getAttribute('data-target-width');
      });
    }, 100);
  }
}

async function togglePREditMode() {
  const btn = document.getElementById('prEditBtn');
  const btnText = document.getElementById('prBtnText');
  const icon = document.getElementById('prEditIcon');

  if (!isPREditMode) {
    isPREditMode = true;
    btn.style.background = 'var(--green-bg)';
    btn.style.borderColor = 'var(--green)';
    btn.style.color = 'var(--green)';
    btnText.innerText = 'Kaydet';
    icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path>';
    renderPRList(_currentUser.username);
    return;
  }

  const newTargets = {};
  TARGET_COMPOUNDS.forEach(ex => {
    const input = document.getElementById(`pr_input_${ex.key}`);
    newTargets[ex.key] = parseFloat(input?.value) || 0;
  });

  btn.disabled = true;
  btnText.innerText = 'Kaydediliyor…';
  try {
    const result = await apiPost('/api/dashboard/preferences/pr-targets', {
      pr_targets: newTargets
    });
    applyDashboardPreferences(result.dashboard_preferences);
    isPREditMode = false;
    btn.style.background = 'transparent';
    btn.style.borderColor = 'var(--accent)';
    btn.style.color = 'var(--accent)';
    btnText.innerText = 'Düzenle';
    icon.innerHTML = '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path>';
    renderPRList(_currentUser.username);
    toast('PR hedefleri hesabınıza kaydedildi.', 'success');
  } catch (error) {
    btnText.innerText = 'Kaydet';
    toast(error.message || 'PR hedefleri kaydedilemedi.', 'error');
  } finally {
    btn.disabled = false;
  }
}

/* ═══════════════════════════════════════════════
   SPLIT SEKMESİ (GEÇİŞ VE ÇİZİM MANTIĞI)
═══════════════════════════════════════════════ */
function switchSplitMode(mode) {
  localStorage.setItem('selectedSplitMode', mode);

  const customBtn = document.getElementById('btnSplitCustom');
  const expertBtn = document.getElementById('btnSplitExpert');

  if(customBtn && expertBtn) {
    if (mode === 'custom') {
      customBtn.style.background = 'var(--accent)';
      customBtn.style.color = '#ffffff';
      expertBtn.style.background = 'transparent';
      expertBtn.style.color = 'var(--text-muted)';
    } else {
      expertBtn.style.background = 'var(--accent)';
      expertBtn.style.color = '#ffffff';
      customBtn.style.background = 'transparent';
      customBtn.style.color = 'var(--text-muted)';
    }
  }

  renderSelectedSplit(mode);
  refreshDashboardProgramStat(mode);
}

function renderSelectedSplit(mode) {
  const container = document.getElementById('splitDays');
  const badge = document.getElementById('splitBadge');
  if (!container || !cachedUserData) return;

  if (mode === 'custom') {
    let customSplit = [];
    try {
      if (cachedUserData.user?.custom_split && cachedUserData.user.custom_split !== '[]') {
          customSplit = JSON.parse(cachedUserData.user.custom_split);
      }
    } catch (e) { console.error("Özel split okuma hatası:", e); }

    if (customSplit.length > 0) {
      const currentWeekNum = getWeekNum(new Date());
      const activeIndex = currentWeekNum % customSplit.length;
      const weekData = customSplit[activeIndex];

      if(badge) {
        badge.textContent = `Özel (${activeIndex + 1}. Hafta)`;
        badge.className = "badge badge-accent";
      }

      drawSplitDaysHTML(weekData, true, { activeWeekIndex: activeIndex });

    } else {
      if(badge) {
        badge.textContent = "Özel Program Yok";
        badge.className = "badge badge-secondary";
      }
      container.innerHTML = `
        <div style="text-align:center; padding:20px; color:var(--text-muted); font-size:13px;">
          <p>Henüz kendi özel programını kurgulamadın.</p>
          <button onclick="navigate('custom-program', this)"
                  style="margin-top:10px; padding:8px 16px; background:var(--accent-soft); border:1px solid var(--accent); color:var(--accent); border-radius:6px; font-weight:700; cursor:pointer;">
               Hemen Özel Program Yaz
          </button>
        </div>
      `;
    }
  } else {
    const recommendation = expertRecommendationFromData(cachedUserData);
    if (recommendation) {
      const active = expertRecommendationWeek(recommendation);
      if (badge) {
        badge.textContent = `${recommendation.name || 'Uzman Önerisi'} · ${active.index + 1}. Hafta`;
        badge.className = "badge badge-accent";
      }
      drawSplitDaysHTML(active.days, true, { kind: 'expert-recommendation', activeWeekIndex: active.index });
      return;
    }
    if(badge) {
      badge.textContent = cachedUserData.split_info?.split || "Uzman Önerisi";
      badge.className = "badge badge-accent";
    }
    const expertDays = cachedUserData.split_info?.days || [];
    drawSplitDaysHTML(expertDays, true, null);
  }
}

function queueCustomSplitOrderSave(reorderedWeek, activeWeekIndex) {
  if (!cachedUserData?.user || !Number.isInteger(activeWeekIndex)) return;

  let program;
  try {
    program = JSON.parse(cachedUserData.user.custom_split || '[]');
  } catch (_) {
    toast('Özel program okunamadığı için sıra kaydedilemedi.', 'error');
    return;
  }
  if (!Array.isArray(program) || !Array.isArray(program[activeWeekIndex])) return;

  // DOM’daki diziyi derin kopyalayarak kayıt sırasında sonradan değişmesini engelleriz.
  program[activeWeekIndex] = reorderedWeek.map(day => ({ ...day }));
  const nextProgramJson = JSON.stringify(program);
  const username = cachedUserData.user.username || window._currentUsername || _currentUser?.username;
  if (!username) {
    toast('Oturum bilgisi bulunamadı; sıra kaydedilemedi.', 'error');
    return;
  }

  cachedUserData.user.custom_split = nextProgramJson;
  const saveVersion = ++customSplitSaveVersion;
  toast('Program sırası kaydediliyor…', 'info');

  // Kayıtları sıraya alır; hızlı arka arkaya sürüklemelerde son durum kaybolmaz.
  customSplitSaveQueue = customSplitSaveQueue.then(async () => {
    try {
      await apiPost('/api/custom-program', { username, program });
      lastConfirmedCustomSplitJson = nextProgramJson;
      if (saveVersion === customSplitSaveVersion) {
        toast('Program sırası hesabınıza kaydedildi.', 'success');
      }
    } catch (error) {
      if (saveVersion === customSplitSaveVersion) {
        cachedUserData.user.custom_split = lastConfirmedCustomSplitJson;
        renderSelectedSplit('custom');
        toast(error.message || 'Program sırası kaydedilemedi; son kayıtlı düzene geri dönüldü.', 'error');
      }
    }
  });
}


function queueExpertRecommendationOrderSave(reorderedWeek, activeWeekIndex) {
  const recommendation = expertRecommendationFromData(cachedUserData);
  if (!recommendation || !recommendation.weeks?.[activeWeekIndex]) return;
  recommendation.weeks[activeWeekIndex].days = reorderedWeek.map(day => ({ ...day }));
  if (expertDataState) expertDataState.recommendation = recommendation;
  expertRecommendationSaveQueue = expertRecommendationSaveQueue.then(async () => {
    try {
      const result = await apiPut('/api/expert-data/recommendation/reorder', { weeks: recommendation.weeks });
      if (cachedUserData) {
        cachedUserData.dashboard_preferences = result.dashboard_preferences || cachedUserData.dashboard_preferences;
      }
      if (expertDataState) expertDataState.recommendation = result.recommendation || recommendation;
      toast('Uzman önerisi sıra düzeni kaydedildi.', 'success');
    } catch (error) {
      toast(error.message || 'Uzman önerisi sırası kaydedilemedi.', 'error');
      if (cachedUserData) await loadDashboard(cachedUserData.user?.username || _currentUser?.username || '');
    }
  });
}

// 1. ADIM: Fonksiyona "shouldAnimate = true" varsayılan parametresi eklendi
function drawSplitDaysHTML(daysList, shouldAnimate = true, reorderContext = null) {
  if (!document.getElementById('sortable-css')) {
    const style = document.createElement('style');
    style.id = 'sortable-css';
    style.innerHTML = `
      .sortable-ghost { opacity: 0.3 !important; background: rgba(255,255,255,0.05) !important; border-radius: 10px; }
      .drag-handle:active { cursor: grabbing !important; color: var(--accent) !important; }

      @keyframes slideDownCard {
        0% { opacity: 0; transform: translateY(-20px); }
        100% { opacity: 1; transform: translateY(0); }
      }
      .animate-slide-down {
        opacity: 0;
        animation: slideDownCard 0.4s cubic-bezier(0.25, 1, 0.5, 1) forwards;
        animation-delay: calc(var(--card-index, 0) * 0.08s);
      }
    `;
    document.head.appendChild(style);
  }

  const daysName = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const weekStart = new Date(today);
  const dayOfWeek = today.getDay() === 0 ? 6 : today.getDay() - 1;
  weekStart.setDate(today.getDate() - dayOfWeek);

  const completedDates = cachedUserData?.sessions ? cachedUserData.sessions.map(sess => sess.date) : [];

  let bgHTML = '<div style="position:absolute; top:0; left:0; right:0; bottom:0; display:flex; flex-direction:column; gap:8px; z-index:1;">';
  let fgHTML = '<div id="fgSortableList" style="position:relative; z-index:2; display:flex; flex-direction:column; gap:8px;">';

  for (let i = 0; i < 7; i++) {
    const d = new Date(weekStart);
    d.setDate(weekStart.getDate() + i);
    d.setHours(0, 0, 0, 0);

    const dateStr = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const isToday = d.getTime() === today.getTime();
    const isPast = d.getTime() < today.getTime();

    const dayData = daysList[i] || { type: 'Rest Day', isRest: true };
    const workoutType = dayData.type || dayData.session_type || 'Dinlenme';
    const isRest = dayData.isRest || workoutType.toLowerCase().includes('rest') || workoutType.toLowerCase().includes('dinlenme');

    let statusClass = '';
    let statusIcon = `<svg style="width:18px; height:18px; color:rgba(255,255,255,0.15);" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>`;

    if (completedDates.includes(dateStr)) {
      statusClass = 'split-done';
      statusIcon = `<svg style="width:20px; height:20px; color:var(--green, #22c55e);" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7"></path></svg>`;
    } else if (isPast && !isRest) {
      statusClass = 'split-missed';
      statusIcon = `<svg style="width:20px; height:20px; color:var(--red, #ef4444);" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12"></path></svg>`;
    } else if (isToday) {
      statusClass = 'split-today';
      statusIcon = `<span style="font-size:10px; font-weight:700; color:var(--accent); background:var(--accent-soft); padding:3px 8px; border-radius:12px; letter-spacing:0.3px;">BUGÜN</span>`;
    }

    // 2. ADIM: Sadece shouldAnimate "true" ise animasyon kodlarını ekliyoruz!
    const animClass = shouldAnimate ? 'animate-slide-down' : '';
    const animStyle = shouldAnimate ? `--card-index: ${i};` : '';

    bgHTML += `
      <div class="split-card ${statusClass} ${animClass}" style="${animStyle} height:64px; margin:0; padding:0 16px; border-radius:10px; display:flex; align-items:center; justify-content:space-between;">
         <div style="display:flex; flex-direction:column; align-items:center; justify-content:center; min-width:50px;">
            <span style="font-size:13px; font-weight:700; white-space:nowrap;">Gün ${i+1}</span>
            <span style="font-size:10px; color:var(--text-muted); font-weight:600; text-transform:uppercase;">${daysName[i]}</span>
         </div>
         <div style="display:flex; align-items:center; justify-content:center; min-width:24px;">
            ${statusIcon}
         </div>
      </div>
    `;

    let displayType = workoutType;
    if (workoutType.includes('(')) {
        const parts = workoutType.split('(');
        displayType = `<span style="font-size:14px; font-weight:600; color:var(--text);">${parts[0].trim()}</span>
                       <span style="display:block; font-size:11px; color:var(--text-muted); margin-top:2px;">(${parts[1]}</span>`;
    } else {
        let focusSuffix = dayData.focus ? ` <span style="display:block; font-size:11px; color:var(--text-muted); margin-top:2px;">(${dayData.focus})</span>` : '';
        displayType = `<span style="font-size:14px; font-weight:600; color:var(--text);">${workoutType}</span>${focusSuffix}`;
    }

    fgHTML += `
      <div data-index="${i}" class="${animClass}" style="${animStyle} height:64px; margin:0; padding:0 50px 0 82px; border-radius:10px; display:flex; align-items:center; gap:12px; transition:background 0.2s;"
           onmouseover="this.style.background='rgba(255,255,255,0.03)'" onmouseout="this.style.background='transparent'">
         ${reorderContext ? `
           <div class="drag-handle" title="Kaydırarak yer değiştir" style="cursor:grab; color:rgba(255,255,255,0.15); display:flex; align-items:center; transition:0.2s;"
                onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='rgba(255,255,255,0.15)'">
              <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h16"></path>
              </svg>
           </div>` : '<div style="width:20px; flex:0 0 20px;"></div>'}

         <div class="split-type" style="line-height:1.2; overflow:hidden;">
            ${isRest && !dayData.type ? '<span style="font-size:14px; font-weight:600; color:var(--text);">Dinlenme</span>' : displayType}
         </div>
      </div>
    `;
  }

  bgHTML += '</div>';
  fgHTML += '</div>';

  const splitDaysEl = document.getElementById('splitDays');
  if (splitDaysEl) {
    splitDaysEl.style.position = 'relative';
    // Mobilde 7 gün kartı alt alta ~480px kaplar; ekran genişliğine göre yükseklik ayarlanır.
    splitDaysEl.style.minHeight = (window.innerWidth <= 480) ? '480px' : '496px';
    splitDaysEl.innerHTML = bgHTML + fgHTML;

    if (reorderContext && typeof Sortable !== 'undefined') {
      new Sortable(document.getElementById('fgSortableList'), {
        handle: '.drag-handle',
        animation: 250,
        ghostClass: 'sortable-ghost',
        onEnd: function(evt) {
          const oldIdx = evt.oldIndex;
          const newIdx = evt.newIndex;
          if (oldIdx === newIdx) return;

          const movedItem = daysList.splice(oldIdx, 1)[0];
          daysList.splice(newIdx, 0, movedItem);

          // Sıra önce ekranda korunur, sonra oturum sahibinin sunucu kaydına yazılır.
          drawSplitDaysHTML(daysList, false, reorderContext);
          if (reorderContext.kind === 'expert-recommendation') queueExpertRecommendationOrderSave(daysList, reorderContext.activeWeekIndex);
          else queueCustomSplitOrderSave(daysList, reorderContext.activeWeekIndex);
        }
      });
    }
  }
}

function getWeekNum(d) {
  d = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  var yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}


/* ═══════════════════════════════════════════════
   KAS DAĞILIMI GRAFİĞİ (İLK YÜKLEME VE BUTON ANİMASYONLU)
═══════════════════════════════════════════════ */
function renderMuscleChart(labels, data, details = {}) {
  const ctx = document.getElementById('muscleChart')?.getContext('2d');
  if (!ctx) return;

  // Eski UI renk sırası korunur. Birleşmiş ana gruplar aynı tanıdık rengi alır.
  const colorsByGroup = {
    'Biceps': '#6c63ff', 'Triceps': '#22c55e', 'Göğüs': '#f59e0b', 'Omuz': '#3b82f6',
    'Quadriceps': '#ef4444', 'Hamstring': '#8b5cf6', 'Calf': '#06b6d4', 'Gluteus': '#ec4899',
    'Alt Sırt': '#6c63ff', 'Kol Rotatorları': '#22c55e', 'Trapezler': '#f59e0b',
    'Skapula': '#3b82f6', 'Adductors': '#8b5cf6',
    'Core': '#06b6d4', 'Diğer': '#ec4899'
  };
  const fallbackColors = ['#6c63ff','#22c55e','#f59e0b','#3b82f6','#ef4444','#8b5cf6','#06b6d4','#ec4899'];
  const finalLabels = labels.length ? labels : ['Veri yok'];
  const finalData = data.length ? data : [1];
  const chartColors = finalLabels.map((label, index) => colorsByGroup[label] || fallbackColors[index % fallbackColors.length]);
  const formatSet = value => {
    const number = Number(value || 0);
    return Number.isInteger(number) ? String(number) : number.toFixed(1).replace(/\.0$/, '');
  };

  // 1. EĞER GRAFİK ZATEN VARSA (Butonlara tıklanmışsa çalışan kısım)
  if (window._muscleChart) {
    window._muscleChart.data.labels = finalLabels;
    window._muscleChart.data.datasets[0].data = finalData;
    window._muscleChart.data.datasets[0].backgroundColor = chartColors;
    window._muscleChart.data.datasets[0].muscleDetails = details;
    window._muscleChart.reset();
    window._muscleChart.update();
    return;
  }

  // 2. SAYFA İLK YÜKLENDİĞİNDE ÇALIŞAN KISIM
  window._muscleChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: finalLabels,
      datasets: [{ data: finalData, backgroundColor: chartColors, muscleDetails: details }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: {
        animateRotate: true,
        animateScale: false,
        duration: 1200,
        easing: 'easeOutQuart'
      },
      plugins: {
        legend: {
          position: 'right',
          labels: { color: '#9ca3b4', font: { size: 11 } }
        },
        // Grafik görünümü aynı kalır; yalnız dilim üzerine gelindiğinde
        // alt kas dağılımı ek bilgi olarak görünür.
        tooltip: {
          callbacks: {
            label(context) {
              return `${context.label}: ${formatSet(context.raw)} hareket`;
            },
            afterLabel(context) {
              const hoverGroups = new Set([
                'Omuz', 'Gluteus', 'Alt Sırt', 'Kol Rotatorları', 'Trapezler', 'Skapula',
                'Adductors', 'Core'
              ]);
              if (!hoverGroups.has(context.label)) return '';
              const detailMap = context.dataset.muscleDetails?.[context.label] || {};
              const items = Object.entries(detailMap);
              if (!items.length) return '';
              return ['Alt kaslar:', ...items.map(([name, count]) => `• ${name}: ${formatSet(count)} hareket`)];
            }
          }
        }
      }
    }
  });
  window._muscleChart.reset();
  setTimeout(() => {
    window._muscleChart.update();
  }, 50);
}

/* ═══════════════════════════════════════════════
   ANTRENMAN KAYDI PAGE (AKILLI KONTROL SİSTEMLİ)
═══════════════════════════════════════════════ */
async function loadWorkoutPage() {
  // Set today's date
  const today = new Date();

  // Yerel saate göre (Timezone) doğru bugünü alıp formatlıyoruz
  const offset = today.getTimezoneOffset() * 60000;
  const localTodayStr = (new Date(today - offset)).toISOString().split('T')[0];

  const dateInput = document.getElementById('workoutDate');
  // Genel düzenleme taslağının özgün tarihi, sayfaya geçişte bugünün tarihiyle
  // ezilmemelidir. Yeni kayıt ekranı ise önceki davranışını korur.
  if (_editingWorkoutId === null) dateInput.value = localTodayStr;

  // Takvimde bugünden sonrasını (geleceği) KİLİTLE!
  dateInput.setAttribute('max', localTodayStr);

  // Load exercise pool
  if (_exercisePool.length === 0) {
    try {
      const data = await apiGet('/api/exercises');
      _exercisePool = Array.isArray(data?.exercises) ? data.exercises : [];
      _muscleGroups = Array.isArray(data?.muscle_groups) && data.muscle_groups.length
        ? data.muscle_groups
        : [...DEFAULT_UI_MUSCLE_GROUPS];
      if (_exercisePool.length === 0) throw new Error('Egzersiz havuzu boş döndü');
    } catch (error) {
      console.error('Egzersiz havuzu yüklenemedi:', error);
      _muscleGroups = [...DEFAULT_UI_MUSCLE_GROUPS];
      document.getElementById('muscleFilterList').innerHTML = '<div class="empty-state">Egzersiz havuzu yüklenemedi. Lütfen bağlantınızı kontrol edip sayfayı yenileyin.</div>';
      document.getElementById('exerciseListContainer').innerHTML = '<div class="empty-state">Hareket listesi geçici olarak yüklenemedi.</div>';
      toast('Egzersiz havuzu yüklenemedi', 'error');
      return;
    }
  }

  // Dropdown değiştiğinde filtrelemeyi tetikler ---
  const workoutTypeEl = document.getElementById('workoutType');
  workoutTypeEl.removeEventListener('change', applySessionFilter);
  workoutTypeEl.addEventListener('change', applySessionFilter);

  // Sayfa ilk yüklendiğinde dropdown'da ne seçiliyse ona göre filtrele.
  // Bu işlem genel düzenleme taslağındaki seçili hareketleri değiştirmez.
  applySessionFilter();
  renderSelectedExercises();
  updateWorkoutFormMode();
}

// Seans türü yalnızca görünür hareket listesini filtreler.
// Özel Seans (custom) seçildiğinde havuzdaki tüm kaslar ve hareketler açılır.
// Legs/Lower seçiminde bacak genel etiketi değil, doğrudan alt kaslar sunulur.
const SESSION_MUSCLE_MAP = Object.freeze({
  push: ["Göğüs", "Omuz", "Triceps"],
  pull: ["Sırt", "Biceps"],
  legs: ["Quadriceps", "Hamstring", "Gluteus", "Calf", "Adductors", "Rotatorlar"],
  lower: ["Quadriceps", "Hamstring", "Gluteus", "Calf", "Adductors", "Rotatorlar"],
  upper: ["Göğüs", "Sırt", "Omuz", "Biceps", "Triceps", "Rotatorlar"],
  "full body": ["Göğüs", "Sırt", "Omuz", "Biceps", "Triceps", "Quadriceps", "Hamstring", "Gluteus", "Calf", "Adductors", "Rotatorlar", "Core"],
  arms: ["Biceps", "Triceps"],
  core: ["Core"],
  rotatorlar: ["Rotatorlar"]
});

function getSelectedSessionType() {
  return String(document.getElementById('workoutType')?.value || '').trim().toLowerCase();
}

function getAllowedMusclesForSession() {
  const selectedType = getSelectedSessionType();
  const availableGroups = Array.isArray(_muscleGroups) && _muscleGroups.length
    ? _muscleGroups
    : [...DEFAULT_UI_MUSCLE_GROUPS];
  // Full Body ve Özel Seans, veri henüz bellekten temizlenmiş olsa dahi boş
  // kalmamalıdır. Bu nedenle güvenli sabit UI listesine geri düşer.
  if (selectedType === 'custom') return availableGroups;
  return SESSION_MUSCLE_MAP[selectedType] || availableGroups;
}

// Yeni API'de arka omuz gibi hareketler birden fazla sade filtreye ait olabilir.
// Eski API yanıtları için tekil `muscle` alanına geri düşerek uyumluluk korunur.
function getExerciseDisplayMuscleGroups(exercise) {
  const groups = Array.isArray(exercise?.display_muscle_groups)
    ? exercise.display_muscle_groups.filter(Boolean)
    : [];
  return groups.length ? groups : [String(exercise?.muscle || '').trim()].filter(Boolean);
}

function exerciseMatchesAnyMuscle(exercise, muscles) {
  const allowed = new Set(muscles || []);
  return getExerciseDisplayMuscleGroups(exercise).some(group => allowed.has(group));
}

function exerciseMatchesMuscleFilter(exercise, muscle) {
  const targetPrimaryMuscle = LEG_DETAIL_FILTERS[muscle];
  if (targetPrimaryMuscle) {
    const primary = Array.isArray(exercise?.analysis?.primary_muscles)
      ? exercise.analysis.primary_muscles
      : [];
    return primary.includes(targetPrimaryMuscle);
  }
  return getExerciseDisplayMuscleGroups(exercise).includes(muscle);
}

function replayWorkoutFilterAnimation(...elements) {
  elements.filter(Boolean).forEach(element => {
    element.classList.remove('workout-filter-enter');
    void element.offsetWidth; // Aynı sınıfın tekrar animasyon başlatmasını sağlar.
    element.classList.add('workout-filter-enter');
  });
}

// Seçilen Seans Türüne Göre Kas Gruplarını Filtreler
function applySessionFilter() {
  const allowedMuscles = getAllowedMusclesForSession();
  const filterList = document.getElementById('muscleFilterList');

  filterList.innerHTML = '<div class="muscle-filter active" data-muscle="all" onclick="filterExercises(\'all\',this)">Tümü</div>' +
    allowedMuscles.map(m => `<div class="muscle-filter" data-muscle="${m}" onclick="filterExercises('${m}',this)">${m}</div>`).join('');

  renderExerciseList('all');
  replayWorkoutFilterAnimation(filterList, document.getElementById('exerciseListContainer'));
}

function filterExercises(muscle, el) {
  document.querySelectorAll('.muscle-filter').forEach(f => f.classList.remove('active'));
  el.classList.add('active');
  renderExerciseList(muscle);
}

function renderExerciseList(muscle) {
  const container = document.getElementById('exerciseListContainer');
  const selectedType = getSelectedSessionType();
  let filtered = [];

  if (muscle === 'all') {
    const allowedMuscles = getAllowedMusclesForSession();
    filtered = _exercisePool.filter(exercise => {
      if (exerciseMatchesAnyMuscle(exercise, allowedMuscles)) return true;
      // Deadlift, Legs/Lower seçiliyken Sırt ana grubunda olsa da listede görünür.
      return exercise.name.toLowerCase().includes('deadlift') &&
        (selectedType === 'legs' || selectedType === 'lower');
    });
  } else {
    filtered = _exercisePool.filter(exercise => exerciseMatchesMuscleFilter(exercise, muscle));
  }

  container.innerHTML = filtered.map(ex => {
    const bwLabel = ex.bw ? '<span class="bw-badge">Vücut Ağırlığı</span>' : '';
    const wtLabel = ex.weighted && !ex.bw
      ? '<span class="bw-badge" style="background:var(--blue-bg);color:var(--blue)">Ağırlıklı</span>'
      : '';
    return `<div class="exercise-option" onclick="addExercise('${ex.id}')">${ex.name} ${bwLabel}${wtLabel}</div>`;
  }).join('');

  replayWorkoutFilterAnimation(container);
}

function addExercise(exId) {
  const ex = _exercisePool.find(item => item.id === exId);
  if (!ex) return;

  if (_selectedExercises.find(item => item.canonical_exercise_id === ex.id || item.exercise_id === ex.id)) {
    toast('Bu hareket zaten eklendi', 'info');
    return;
  }

  const loadMode = ex.analysis?.load_mode || (ex.bw ? 'bodyweight' : 'external_load');
  _selectedExercises.push({
    // Kullanıcı sadece ismi seçer. Kimlik, yükleme türü ve meta veri arka planda taşınır.
    exercise_id: ex.id,
    canonical_exercise_id: ex.id,
    exercise_name: ex.name,
    muscle_group: ex.muscle_group || ex.muscle,
    display_muscle: ex.muscle,
    is_bodyweight: Boolean(ex.bw),
    load_mode: loadMode,
    sets_data: [{ reps: 0, weight_kg: 0, rir: null }]
  });

  renderSelectedExercises();
}

function renderSelectedExercises() {
  const container = document.getElementById('selectedExercises');
  container.innerHTML = _selectedExercises.map((ex, idx) => {
    const bodyweightOnly = ex.load_mode === 'bodyweight' || ex.is_bodyweight;
    const extraLoad = ex.load_mode === 'bodyweight_plus_external';
    const loadLabel = extraLoad ? 'Ek yük (kg)' : 'Ağırlık (kg)';
    const muscleLabel = ex.display_muscle || ex.muscle_group;
    return `
      <div class="card history-card-animated selected-exercise-card" data-exercise-index="${idx}" style="margin-bottom:12px; padding:16px; --card-index: ${idx};">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px">
          <div>
            <strong>${ex.exercise_name}</strong>
            <span class="badge ${bodyweightOnly ? 'badge-green' : 'badge-accent'}" style="margin-left:8px">${muscleLabel}</span>
            ${bodyweightOnly ? '<span class="badge badge-green" style="margin-left:4px">Vücut Ağırlığı</span>' : ''}
            ${extraLoad ? '<span class="badge badge-accent" style="margin-left:4px">Vücut Ağırlığı + Ek Yük</span>' : ''}
          </div>
          <button class="btn btn-sm btn-danger" onclick="removeExercise(${idx})">Sil</button>
        </div>
        <table class="sets-table">
          <thead><tr><th>Set</th><th>Tekrar</th><th>${bodyweightOnly ? 'Yük' : loadLabel}</th><th title="Reps In Reserve — sette tahmini kalan tekrar">RIR</th><th></th></tr></thead>
          <tbody>
            ${ex.sets_data.map((s, si) => {
              const rir = Number.isInteger(Number(s.rir)) && Number(s.rir) >= 0 && Number(s.rir) <= 5 ? Number(s.rir) : '';
              return `
              <tr>
                <td><strong>${si + 1}</strong></td>
                <td><input type="number" value="${s.reps}" min="1" max="100" onchange="updateSet(${idx},${si},'reps',this.value)" style="width:70px" /></td>
                <td>${bodyweightOnly
                  ? '<span style="opacity:.58;font-size:12px">Otomatik</span>'
                  : `<input type="number" value="${s.weight_kg}" min="0" max="500" step="0.5" style="width:80px" onchange="updateSet(${idx},${si},'weight_kg',this.value)" />`
                }</td>
                <td><select aria-label="${si + 1}. set RIR" onchange="updateSet(${idx},${si},'rir',this.value)" style="width:78px"><option value="" ${rir === '' ? 'selected' : ''}>—</option>${[0,1,2,3,4,5].map(value => `<option value="${value}" ${rir === value ? 'selected' : ''}>${value}</option>`).join('')}</select></td>
                <td>${si === 0 ? `<button class="btn btn-sm btn-secondary" onclick="addSet(${idx})">+ Set</button>` : `<button class="btn btn-sm btn-danger" onclick="removeSet(${idx},${si})">X</button>`}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
        <div style="margin-top:8px;color:var(--text-muted);font-size:11px">RIR: Bu sette teknik bozulmadan kaç tekrar daha yapabilirdin? <strong>0</strong> = failure'a çok yakın, <strong>1–3</strong> = kontrollü çaba, <strong>4–5</strong> = yüksek tekrar rezervi.</div>
      </div>
    `;
  }).join('');
}

function addSet(exIdx) {
  _selectedExercises[exIdx].sets_data.push({ reps: 0, weight_kg: 0, rir: null });
  renderSelectedExercises();
}
function removeSet(exIdx, setIdx) {
  if (_selectedExercises[exIdx].sets_data.length <= 1) { toast('En az 1 set olmalı', 'error'); return; }
  _selectedExercises[exIdx].sets_data.splice(setIdx, 1);
  renderSelectedExercises();
}
function updateSet(exIdx, setIdx, field, value) {
  if (field === 'rir') {
    const parsed = value === '' ? null : Number(value);
    _selectedExercises[exIdx].sets_data[setIdx].rir = Number.isInteger(parsed) && parsed >= 0 && parsed <= 5 ? parsed : null;
    return;
  }
  _selectedExercises[exIdx].sets_data[setIdx][field] = parseFloat(value) || 0;
}
function removeExercise(idx) {
  const card = document.querySelector(`#selectedExercises [data-exercise-index="${idx}"]`);
  const finalizeRemoval = () => {
    _selectedExercises.splice(idx, 1);
    renderSelectedExercises();
  };

  // Animasyon desteklenmiyorsa veya kart bulunamazsa veri akışı yine sorunsuz sürer.
  if (!card || window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    finalizeRemoval();
    return;
  }

  card.classList.add('is-removing');
  card.addEventListener('animationend', finalizeRemoval, { once: true });
}

function updateWorkoutFormMode() {
  const isEditing = _editingWorkoutId !== null;
  const title = document.getElementById('workoutPageTitle');
  const subtitle = document.getElementById('workoutPageSubtitle');
  const saveLabel = document.getElementById('saveWorkoutButtonLabel');
  const cancelButton = document.getElementById('cancelWorkoutEditButton');

  if (title) title.textContent = isEditing ? 'Antrenmanı Düzenle' : 'Antrenman Kaydı';
  if (subtitle) subtitle.textContent = isEditing
    ? 'Değişiklikler yalnızca Antrenmanı Güncelle seçildiğinde kaydedilir'
    : 'Yeni bir antrenman seansı kaydet';
  if (saveLabel) saveLabel.textContent = isEditing ? 'Antrenmanı Güncelle' : 'Kaydet';
  if (cancelButton) cancelButton.style.display = isEditing ? 'inline-flex' : 'none';
}

function resetWorkoutFormToNewMode() {
  _editingWorkoutId = null;
  _selectedExercises = [];

  const dateInput = document.getElementById('workoutDate');
  if (dateInput) {
    const today = new Date();
    const offset = today.getTimezoneOffset() * 60000;
    dateInput.value = new Date(today - offset).toISOString().split('T')[0];
  }
  const typeInput = document.getElementById('workoutType');
  if (typeInput) typeInput.value = 'Push';
  const notesInput = document.getElementById('workoutNotes');
  if (notesInput) notesInput.value = '';

  renderSelectedExercises();
  applySessionFilter();
  updateWorkoutFormMode();
}

function cancelWorkoutEdit() {
  if (_editingWorkoutId === null) return;
  resetWorkoutFormToNewMode();
  toast('Genel düzenleme taslağı iptal edildi. Kayıt değiştirilmedi.', 'info');
}

// ── YENİ VE TERTEMİZ KAYDETME FONKSİYONU ──
async function saveWorkout() {
  if (_selectedExercises.length === 0) {
    toast('En az 1 egzersiz ekleyin', 'error');
    return;
  }

  // Kullanıcı tarihi hacklerse (geleceği girerse) engelle!
  const selectedDateStr = document.getElementById('workoutDate').value;
  const selectedDate = new Date(selectedDateStr);
  selectedDate.setHours(0,0,0,0);

  const today = new Date();
  today.setHours(0,0,0,0);

  if (selectedDate > today) {
    toast('Gelecek bir tarihe antrenman kaydedemezsiniz!', 'error');
    return; // Kayıt işlemini durdur!
  }

  const selectedType = document.getElementById('workoutType').value;

  const data = {
    date: selectedDateStr,
    session_type: selectedType,
    notes: document.getElementById('workoutNotes').value,
    exercises: _selectedExercises.map(ex => ({
      exercise_id: ex.exercise_id,
      canonical_exercise_id: ex.canonical_exercise_id || ex.exercise_id,
      exercise_name: ex.exercise_name,
      muscle_group: ex.muscle_group,
      is_bodyweight: ex.is_bodyweight,
      exercise_meta_version: 1,
      sets_data: ex.sets_data
    }))
  };

  try {
    const isEditing = _editingWorkoutId !== null;
    if (isEditing) {
      // Genel düzenleme modunda POST kullanılmaz: aynı workout kimliği güncellenir.
      await apiPut(`/api/workouts/${_editingWorkoutId}`, data);
      toast('Antrenman başarıyla güncellendi!', 'success');
    } else {
      await apiPost(`/api/workouts`, data);
      toast('Antrenman başarıyla kaydedildi!', 'success');
    }

    resetWorkoutFormToNewMode();

    // Antrenman kaydedildikten sonra PR, XP ve İlerleme verilerini güncellemesi için Dashboard sayfasına yönlendir (Opsiyonel ama şık olur)
    navigate('dashboard');
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

function clearWorkout() {
  _selectedExercises = [];
  renderSelectedExercises();
  document.getElementById('workoutNotes').value = '';
}

/* ═══════════════════════════════════════════════
   HISTORY (GEÇMİŞ) - ANA MOTOR VE SEKME YÖNETİMİ
═══════════════════════════════════════════════ */
window.switchHistoryTab = function(tabName) {
  const workContainer = document.getElementById('historyContainer_workout');
  const nutContainer = document.getElementById('historyContainer_nutrition');
  const workTab = document.getElementById('tabWorkoutHistory');
  const nutTab = document.getElementById('tabNutritionHistory');

  if (workContainer) workContainer.style.display = 'none';
  if (nutContainer) nutContainer.style.display = 'none';

  if (workTab) workTab.classList.remove('active');
  if (nutTab) nutTab.classList.remove('active');

  if (tabName === 'workout') {
    if (workContainer) workContainer.style.display = 'flex';
    if (workTab) workTab.classList.add('active');
  } else if (tabName === 'nutrition') {
    if (nutContainer) nutContainer.style.display = 'flex';
    if (nutTab) nutTab.classList.add('active');

    if (typeof loadNutritionHistory === 'function') {
      loadNutritionHistory();
    }
  }
};

/* HX_SET_BASED_RIR_V1 */
/* ═══════════════════════════════════════════════
   1. BÖLÜM: ANTRENMAN GEÇMİŞİ KODLARI
═══════════════════════════════════════════════ */
let globalHistoryWorkouts = [];

async function loadHistory(username) {
  window._currentUsername = username;

  const container = document.getElementById('historyContainer');
  if (!container) return;

  try {
    const workouts = await apiGet(`/api/workouts`);
    globalHistoryWorkouts = workouts;

    if (!workouts || workouts.length === 0) {
      container.innerHTML = `<div class="card" style="text-align:center; padding:30px; color:var(--text-muted);">Henüz kaydedilmiş antrenman geçmişin bulunmuyor.</div>`;
      return;
    }

    let html = '';

    workouts.forEach((w, index) => {
      let exercises = [];
      try { exercises = typeof w.exercises === 'string' ? JSON.parse(w.exercises) : w.exercises || []; } catch(e) {}

      let summaryExHTML = '';
      let fullExHTML = '';

      exercises.forEach((ex, exIdx) => {
        const sets = ex.sets_data || [];

        summaryExHTML += `
          <div class="history-ex-item" style="padding: 2px 6px; margin-bottom: 2px; background: rgba(255,255,255,0.02); border-radius: 4px;">
            <span style="font-size: 13px; font-weight:600; color:var(--text);">${ex.exercise_name || 'Egzersiz'}</span>
            <span class="badge badge-accent" style="font-size:11px; padding: 1px 6px;">${sets.length} Set</span>
          </div>
        `;

        let setsRows = '';
        sets.forEach((s, sIdx) => {
          setsRows += `
            <tr>
              <td style="color:var(--text-muted);">${sIdx + 1}. Set</td>
              <td>
                <span class="view-mode-${index}"><strong>${s.weight_kg || 0}</strong> kg</span>
                <input type="number" step="0.5" class="edit-mode-${index} edit-input" data-ex="${exIdx}" data-set="${sIdx}" data-field="weight_kg" value="${s.weight_kg || 0}" style="display:none; width:60px;">
                <span class="edit-mode-${index}" style="display:none; color:var(--text-muted); font-size:11px;">kg</span>
              </td>
              <td>
                <span class="view-mode-${index}"><strong>${s.reps || 0}</strong> Tekrar</span>
                <input type="number" class="edit-mode-${index} edit-input" data-ex="${exIdx}" data-set="${sIdx}" data-field="reps" value="${s.reps || 0}" style="display:none; width:50px;">
                <span class="edit-mode-${index}" style="display:none; color:var(--text-muted); font-size:11px;">tekrar</span>
              </td>
              <td>
                <span class="view-mode-${index}">${s.rir === 0 || s.rir ? `<strong>${s.rir}</strong> RIR` : 'RIR yok'}</span>
                <input type="number" min="0" max="5" class="edit-mode-${index} edit-input" data-ex="${exIdx}" data-set="${sIdx}" data-field="rir" value="${s.rir === 0 || s.rir ? s.rir : ''}" placeholder="—" style="display:none; width:50px;">
              </td>
            </tr>
          `;
        });

        fullExHTML += `
          <div style="margin-bottom:12px;">
            <div style="font-weight:700; color:var(--accent); font-size:13px; margin-bottom:4px;">${exIdx + 1}. ${ex.exercise_name}</div>
            <table class="set-table">
              <thead><tr><th>Set</th><th>Ağırlık</th><th>Tekrar</th><th>RIR</th></tr></thead>
              <tbody>${setsRows}</tbody>
            </table>
          </div>
        `;
      });

      /* ═══ NOT BÖLÜMÜ ═══ */
      let notesSection = '';
      if (w.notes && w.notes.trim() !== '') {
        notesSection = `
          <div style="margin-top: 8px; padding: 8px 10px; background: rgba(108,99,255,0.06); border-left: 3px solid var(--accent); border-radius: 6px;">
            <div style="font-size: 11px; font-weight: 700; color: var(--accent); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">📝 Not</div>
            <span class="view-mode-${index}" style="font-size: 12px; color: var(--text-muted); line-height: 1.5;">${w.notes}</span>
            <textarea class="edit-mode-${index} edit-input" data-field="notes" style="display:none; width:100%; min-height:60px; padding:6px 8px; font-size:12px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:var(--text); resize:vertical; outline:none;" placeholder="Antrenman notunuz...">${w.notes || ''}</textarea>
          </div>
        `;
      } else {
        notesSection = `
          <div style="margin-top: 8px; padding: 6px 10px; background: rgba(255,255,255,0.02); border-left: 3px solid rgba(255,255,255,0.1); border-radius: 6px; display:none;" class="edit-mode-${index}">
            <textarea class="edit-input" data-field="notes" style="width:100%; min-height:60px; padding:6px 8px; font-size:12px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:var(--text); resize:vertical; outline:none;" placeholder="Antrenman notunuz..."></textarea>
          </div>
        `;
      }
      /* ═══ NOT BÖLÜMÜ SONU ═══ */

      html += `
        <div class="card history-card history-card-animated" id="card-${index}" style="--card-index: ${index};" onclick="handleCardClick(${index}, event)">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px;">
            <div>
              <div style="font-size:16px; font-weight:700; color:var(--text);">${w.session_type || 'Antrenman'} <span class="badge badge-accent" style="font-size:10px; margin-left:6px;">${exercises.length} Hareket</span></div>
              <div style="font-size:12px; color:var(--text-muted); margin-top:4px;">${formatDateTR(w.date)}</div>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <div style="text-align:right; margin-right:8px;">
                <div style="font-size:14px; font-weight:700; color:var(--accent);">${Math.round(w.total_volume).toLocaleString()} kg</div>
              </div>
              <button id="edit-btn-${index}" onclick="toggleEditMode(${index}, event)" title="Setleri Düzenle" style="background:transparent; border:none; color:var(--accent); cursor:pointer; padding:6px; transition:0.2s;"><svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg></button>
              <button onclick="openWorkoutGeneralEdit(${index}, event)" title="Genel Düzenle" class="btn btn-sm btn-secondary" style="white-space:nowrap;">Genel Düzenle</button>
              <button id="save-btn-${index}" onclick="saveEdit(${index}, ${w.id}, event)" title="Kaydet" style="display:none; background:var(--green-bg); border:1px solid var(--green); color:var(--green); font-size:12px; font-weight:700; border-radius:6px; padding:4px 10px; cursor:pointer;">Kaydet</button>
              <button onclick="deleteWorkout(${w.id}, event)" title="Sil" style="background:transparent; border:none; color:#ef4444; cursor:pointer; padding:6px; transition:0.2s;"><svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
            </div>
          </div>

          <div id="hint-${index}" style="text-align:center; font-size:11px; color:var(--text-muted); margin-top:8px; font-weight:600;">Antrenman özetini görmek için tıkla</div>
          <div class="smooth-collapse" id="summary-wrapper-${index}">
            <div class="smooth-collapse-inner" style="margin-top:10px; border-top: 1px solid rgba(255,255,255,0.05); padding-top:10px;">
              ${summaryExHTML}
              ${notesSection}
              <button class="btn-more-details" id="btn-more-${index}" onclick="toggleFullDetails(${index}, event)">Daha Fazla (Set & Ağırlık Detayları)</button>
            </div>
          </div>
          <div class="smooth-collapse" id="full-wrapper-${index}" onclick="handleDetailsClick(${index}, event)">
            <div class="smooth-collapse-inner history-full-box">
              <div style="font-size:12px; font-weight:700; color:var(--accent); margin-bottom:10px;">DETAYLI SET VERİLERİ</div>
              ${fullExHTML}
            </div>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  } catch(e) {
    console.error("Geçmiş yükleme hatası:", e);
  }
}

function handleCardClick(index, event) {
  if (event.target.closest('button, input, textarea')) return;
  const summaryWrap = document.getElementById(`summary-wrapper-${index}`);
  const fullWrap = document.getElementById(`full-wrapper-${index}`);
  const hint = document.getElementById(`hint-${index}`);

  if (fullWrap.classList.contains('open')) {
    closeFullDetails(index);
    if(hint) hint.textContent = 'Özeti kapatmak için tıkla';
    return;
  }

  if (summaryWrap.classList.contains('open')) {
    summaryWrap.classList.remove('open');
    if(hint) hint.textContent = 'Antrenman özetini görmek için tıkla';
    resetEditState(index);
  } else {
    summaryWrap.classList.add('open');
    if(hint) hint.textContent = 'Özeti kapatmak için tıkla';
  }
}

function handleDetailsClick(index, event) {
  if (event.target.closest('button, input, textarea')) return;
  event.stopPropagation();
  const hint = document.getElementById(`hint-${index}`);
  if(hint) hint.textContent = 'Özeti kapatmak için tıkla';
  closeFullDetails(index);
}

function toggleFullDetails(index, event) {
  if (event) event.stopPropagation();
  const fullWrap = document.getElementById(`full-wrapper-${index}`);
  const btnMore = document.getElementById(`btn-more-${index}`);
  const hint = document.getElementById(`hint-${index}`);

  if (fullWrap.classList.contains('open')) {
    closeFullDetails(index);
    if(hint) hint.textContent = 'Özeti kapatmak için tıkla';
  } else {
    fullWrap.classList.add('open');
    if(btnMore) btnMore.textContent = 'Daha Az Göster';
    if(hint) hint.textContent = 'Kapatmak için tıkla';
  }
}

function closeFullDetails(index) {
  const fullWrap = document.getElementById(`full-wrapper-${index}`);
  const btnMore = document.getElementById(`btn-more-${index}`);
  if (fullWrap) fullWrap.classList.remove('open');
  if (btnMore) btnMore.textContent = 'Daha Fazla (Set & Ağırlık Detayları)';
  resetEditState(index);
}

function resetEditState(index) {
  const views = document.querySelectorAll(`.view-mode-${index}`);
  const edits = document.querySelectorAll(`.edit-mode-${index}`);
  views.forEach(el => el.style.display = '');
  edits.forEach(el => el.style.display = 'none');
  const editBtn = document.getElementById(`edit-btn-${index}`);
  const saveBtn = document.getElementById(`save-btn-${index}`);
  if(editBtn) editBtn.style.display = 'inline-block';
  if(saveBtn) saveBtn.style.display = 'none';
}

function toggleEditMode(index, event) {
  if (event) event.stopPropagation();
  const summaryWrap = document.getElementById(`summary-wrapper-${index}`);
  const fullWrap = document.getElementById(`full-wrapper-${index}`);

  if (!summaryWrap.classList.contains('open')) summaryWrap.classList.add('open');
  if (!fullWrap.classList.contains('open')) fullWrap.classList.add('open');

  document.getElementById(`hint-${index}`).textContent = 'Düzenleme Modu Açık (İptal için karta tıkla)';
  document.getElementById(`btn-more-${index}`).textContent = 'Daha Az Göster';

  const views = document.querySelectorAll(`.view-mode-${index}`);
  const edits = document.querySelectorAll(`.edit-mode-${index}`);
  views.forEach(el => el.style.display = 'none');
  edits.forEach(el => el.style.display = 'inline-block');

  document.getElementById(`edit-btn-${index}`).style.display = 'none';
  document.getElementById(`save-btn-${index}`).style.display = 'inline-block';
}

function buildWorkoutDraftExercise(rawExercise) {
  const raw = rawExercise && typeof rawExercise === 'object' ? rawExercise : {};
  const rawId = raw.exercise_id || raw.canonical_exercise_id || '';
  const catalogExercise = _exercisePool.find(item =>
    item.id === rawId || item.id === raw.canonical_exercise_id || item.name === raw.exercise_name
  );
  const isBodyweight = typeof raw.is_bodyweight === 'boolean'
    ? raw.is_bodyweight
    : Boolean(catalogExercise?.bw);
  const storedSets = Array.isArray(raw.sets_data) ? raw.sets_data : [];

  return {
    exercise_id: String(raw.exercise_id || catalogExercise?.id || raw.canonical_exercise_id || ''),
    canonical_exercise_id: String(raw.canonical_exercise_id || raw.exercise_id || catalogExercise?.id || ''),
    exercise_name: raw.exercise_name || raw.name || catalogExercise?.name || 'Egzersiz',
    muscle_group: raw.muscle_group || catalogExercise?.muscle_group || catalogExercise?.muscle || 'Diğer',
    display_muscle: catalogExercise?.muscle || raw.muscle_group || 'Diğer',
    is_bodyweight: isBodyweight,
    load_mode: raw.load_mode || catalogExercise?.analysis?.load_mode || (isBodyweight ? 'bodyweight' : 'external_load'),
    // Yeni dizi oluşturulur; taslak üzerinde yapılan hiçbir değişiklik geçmiş
    // listesindeki nesneyi veya veritabanını Kaydet'e kadar etkileyemez.
    sets_data: (storedSets.length ? storedSets : [{ reps: 0, weight_kg: 0, rir: null }]).map(set => ({
      reps: Number(set?.reps) || 0,
      weight_kg: Number(set?.weight_kg) || 0,
      rir: Number.isInteger(Number(set?.rir)) && Number(set?.rir) >= 0 && Number(set?.rir) <= 5 ? Number(set.rir) : null
    }))
  };
}

async function openWorkoutGeneralEdit(index, event) {
  if (event) event.stopPropagation();
  const workout = globalHistoryWorkouts[index];
  if (!workout?.id) {
    toast('Düzenlenecek antrenman bulunamadı.', 'error');
    return;
  }

  let storedExercises = [];
  try {
    storedExercises = typeof workout.exercises === 'string'
      ? JSON.parse(workout.exercises)
      : (Array.isArray(workout.exercises) ? workout.exercises : []);
  } catch (error) {
    toast('Antrenman hareketleri okunamadı.', 'error');
    return;
  }

  // Bu aşama yalnızca istemci tarafında bir taslak oluşturur; API isteği yapılmaz.
  _editingWorkoutId = workout.id;
  _selectedExercises = storedExercises.map(buildWorkoutDraftExercise);

  await navigate('workout');

  const dateInput = document.getElementById('workoutDate');
  if (dateInput) dateInput.value = String(workout.date || '').slice(0, 10);

  const typeInput = document.getElementById('workoutType');
  if (typeInput) {
    const sessionType = String(workout.session_type || 'Custom');
    if (!Array.from(typeInput.options).some(option => option.value === sessionType)) {
      const legacyOption = new Option(sessionType, sessionType);
      typeInput.add(legacyOption);
    }
    typeInput.value = sessionType;
  }

  const notesInput = document.getElementById('workoutNotes');
  if (notesInput) notesInput.value = workout.notes || '';

  applySessionFilter();
  renderSelectedExercises();
  updateWorkoutFormMode();
  toast('Antrenman taslak olarak açıldı. Kaydetmeden hiçbir kayıt değişmez.', 'info');
}

async function saveEdit(index, workoutId, event) {
  if (event) event.stopPropagation();
  const username = window._currentUsername;

  const workout = globalHistoryWorkouts[index];
  let exercises = typeof workout.exercises === 'string' ? JSON.parse(workout.exercises) : workout.exercises;

  const inputs = document.querySelectorAll(`input.edit-mode-${index}, select.edit-mode-${index}`);
  inputs.forEach(input => {
    const exIdx = input.getAttribute('data-ex');
    const setIdx = input.getAttribute('data-set');
    const field = input.getAttribute('data-field');
    const val = parseFloat(input.value);
    if (field === 'weight_kg') { exercises[exIdx].sets_data[setIdx].weight_kg = val; }
    else if (field === 'reps') { exercises[exIdx].sets_data[setIdx].reps = val; }
    else if (field === 'rir') { exercises[exIdx].sets_data[setIdx].rir = Number.isInteger(val) && val >= 0 && val <= 5 ? val : null; }
  });

  try {
    const noteInput = document.querySelector(`textarea.edit-mode-${index}[data-field="notes"]`);
    if (noteInput) {
      workout.notes = noteInput.value;
    }
    await apiPut(`/api/workouts/${workoutId}`, { exercises: exercises, notes: workout.notes || '' });
    toast('Antrenman seti başarıyla güncellendi!', 'success');
    loadHistory(username);
  } catch (err) {
    toast('Güncelleme hatası: ' + err.message, 'error');
  }
}

async function deleteWorkout(id, event) {
  if (event) event.stopPropagation();
  if (!confirm('Bu antrenmanı silmek istediğinize emin misiniz?')) return;
  const username = window._currentUsername;
  try {
    await apiDelete(`/api/workouts/${id}`);
    toast('Antrenman başarıyla silindi!', 'success');
    loadHistory(username);
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}


/* ═══════════════════════════════════════════════
   2. BÖLÜM: BESLENME GEÇMİŞİ (NOTLAR ENTEGRELİ)
═══════════════════════════════════════════════ */

let globalNutritionHistory = [];

async function loadNutritionHistory() {
  const container = document.getElementById('historyContainer_nutrition');
  const username = window._currentUsername;

  if (!container || !username) return;

  try {
    container.innerHTML = `<div style="text-align:center; padding:20px; color:var(--text-muted);">Veriler yükleniyor...</div>`;

    const res = await apiGet(`/api/nutrition/history`);
    globalNutritionHistory = res.history || [];

    if (globalNutritionHistory.length === 0) {
      container.innerHTML = `<div class="card" style="text-align:center; padding:30px; color:var(--text-muted);">Henüz kaydedilmiş beslenme geçmişin bulunmuyor.</div>`;
      return;
    }

    let html = '';
    const targetCal = typeof cachedUserData !== 'undefined' ? (cachedUserData?.stats?.target_calories || 2500) : 2500;

    globalNutritionHistory.forEach((log, index) => {
      let calColor = log.calories >= targetCal ? 'var(--green, #22c55e)' : 'var(--orange, #f59e0b)';

      /* ═══ BESLENME NOT BÖLÜMÜ ═══ */
      let nutriNotesSection = '';
      if (log.notes && log.notes.trim() !== '') {
        nutriNotesSection = `
          <div style="margin-top: 10px; padding: 8px 10px; background: rgba(108,99,255,0.06); border-left: 3px solid var(--accent); border-radius: 6px;">
            <div style="font-size: 11px; font-weight: 700; color: var(--accent); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">📝 Beslenme Notu</div>
            <span class="nutri-view-${index}" style="font-size: 12px; color: var(--text-muted); line-height: 1.5; display: block;">${log.notes}</span>
            <textarea class="nutri-edit-${index} edit-input" id="n-edit-notes-${index}" style="display:none; width:100%; min-height:60px; padding:6px 8px; font-size:12px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:var(--text); resize:vertical; outline:none;" placeholder="Beslenme notunuz...">${log.notes || ''}</textarea>
          </div>
        `;
      } else {
        nutriNotesSection = `
          <div style="margin-top: 10px; padding: 8px 10px; background: rgba(255,255,255,0.02); border-left: 3px solid rgba(255,255,255,0.1); border-radius: 6px; display:none;" class="nutri-edit-${index}">
            <div style="font-size: 11px; font-weight: 700; color: var(--text-muted); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">📝 Beslenme Notu Ekle</div>
            <textarea class="edit-input" id="n-edit-notes-${index}" style="width:100%; min-height:60px; padding:6px 8px; font-size:12px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:var(--text); resize:vertical; outline:none;" placeholder="Beslenme notunuz..."></textarea>
          </div>
        `;
      }
      /* ═══ NOT BÖLÜMÜ SONU ═══ */

      html += `
        <div class="card history-card history-card-animated" id="nutri-card-${index}" style="--card-index: ${index}; cursor:pointer; margin-bottom:12px;" onclick="toggleNutritionDetails(${index}, event)">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; flex-wrap:wrap; gap:10px;">
            <div>
              <div class="nutri-view-${index}" style="font-size:15px; font-weight:700; color:var(--text);">${formatDateTR(log.date)}</div>
              <input type="date" class="nutri-edit-${index} edit-input" id="n-edit-date-${index}" value="${log.date}" max="${new Date().toISOString().slice(0, 10)}" aria-label="Kayıt tarihi" style="display:none; width:148px; padding:5px 7px; font-size:12px;">
              <div style="font-size:12px; color:var(--text-muted); margin-top:2px;">Günlük Beslenme Özeti</div>
            </div>
            <div style="display:flex; align-items:center; gap:8px;">
              <div style="text-align:right; margin-right:8px;">
                <span class="nutri-view-${index}" style="font-size:18px; font-weight:800; color:${calColor};">${log.calories} <span style="font-size:12px; font-weight:600; color:var(--text-muted);">kcal</span></span>
              </div>
              <button id="n-edit-btn-${index}" onclick="toggleNutritionEditMode(${index}, event)" title="Düzenle" style="background:transparent; border:none; color:var(--accent); cursor:pointer; padding:6px; transition:0.2s;"><svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"></path></svg></button>
              <button id="n-save-btn-${index}" onclick="saveNutritionEdit(${index}, '${log.date}', event)" title="Kaydet" style="display:none; background:var(--green-bg); border:1px solid var(--green); color:var(--green); font-size:12px; font-weight:700; border-radius:6px; padding:4px 10px; cursor:pointer;">Kaydet</button>
              <button onclick="deleteNutritionLog('${log.date}', event)" title="Sil" style="background:transparent; border:none; color:#ef4444; cursor:pointer; padding:6px; transition:0.2s;"><svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg></button>
            </div>
          </div>
          <div id="nutri-hint-${index}" style="text-align:center; font-size:11px; color:var(--text-muted); margin-top:12px; font-weight:600;">Makro detaylarını görmek için tıkla</div>
          <div class="smooth-collapse" id="nutri-wrapper-${index}">
            <div class="smooth-collapse-inner" style="margin-top:12px; border-top: 1px solid rgba(255,255,255,0.05); padding-top:16px; display:flex; flex-direction:column; gap:16px;">
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:6px; align-items:center;">
                  <span style="color:#22c55e;">🥩 Protein</span>
                  <span class="nutri-view-${index}" style="color:var(--text);">${log.protein}g</span>
                  <input type="number" class="nutri-edit-${index} edit-input" id="n-edit-pro-${index}" value="${log.protein}" style="display:none; width:60px; padding:4px; font-size:12px;">
                </div>
                <div style="width:100%; height:6px; background:rgba(255,255,255,0.05); border-radius:10px;"><div style="width:${Math.min(100, (log.protein/200)*100)}%; height:100%; background:#22c55e; border-radius:10px;"></div></div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:6px; align-items:center;">
                  <span style="color:#f59e0b;">🍞 Karbonhidrat</span>
                  <span class="nutri-view-${index}" style="color:var(--text);">${log.carbs}g</span>
                  <input type="number" class="nutri-edit-${index} edit-input" id="n-edit-carb-${index}" value="${log.carbs}" style="display:none; width:60px; padding:4px; font-size:12px;">
                </div>
                <div style="width:100%; height:6px; background:rgba(255,255,255,0.05); border-radius:10px;"><div style="width:${Math.min(100, (log.carbs/400)*100)}%; height:100%; background:#f59e0b; border-radius:10px;"></div></div>
              </div>
              <div>
                <div style="display:flex; justify-content:space-between; font-size:12px; font-weight:600; margin-bottom:6px; align-items:center;">
                  <span style="color:#3b82f6;">🥑 Yağ</span>
                  <span class="nutri-view-${index}" style="color:var(--text);">${log.fat}g</span>
                  <input type="number" class="nutri-edit-${index} edit-input" id="n-edit-fat-${index}" value="${log.fat}" style="display:none; width:60px; padding:4px; font-size:12px;">
                </div>
                <div style="width:100%; height:6px; background:rgba(255,255,255,0.05); border-radius:10px;"><div style="width:${Math.min(100, (log.fat/100)*100)}%; height:100%; background:#3b82f6; border-radius:10px;"></div></div>
              </div>

              ${nutriNotesSection}

            </div>
          </div>
        </div>
      `;
    });
    container.innerHTML = html;
  } catch(e) {
    console.error("Beslenme geçmişi hatası:", e);
    container.innerHTML = `<div class="card" style="text-align:center; padding:30px; color:var(--red, #ef4444);">
      <div style="font-weight:bold; font-size:16px;">Bağlantı Hatası!</div>
      <div style="font-size:12px; margin-top:8px; opacity:0.8;">Backend sunucusu çalışmıyor veya veri çekilemedi: ${e.message}</div>
    </div>`;
  }
}

window.toggleNutritionDetails = function(index, event) {
  // Textarea'ya veya inputlara basılınca kartın kapanmasını engelle
  if (event.target.closest('button, input, textarea')) return;

  const wrapper = document.getElementById(`nutri-wrapper-${index}`);
  const hint = document.getElementById(`nutri-hint-${index}`);

  if (wrapper.classList.contains('open')) {
    wrapper.classList.remove('open');
    if(hint) hint.textContent = 'Makro detaylarını görmek için tıkla';
    resetNutritionEditState(index);
  } else {
    wrapper.classList.add('open');
    if(hint) hint.textContent = 'Kapatmak için tıkla';
  }
};

function resetNutritionEditState(index) {
  const views = document.querySelectorAll(`.nutri-view-${index}`);
  const edits = document.querySelectorAll(`.nutri-edit-${index}`);
  views.forEach(el => el.style.display = '');
  edits.forEach(el => el.style.display = 'none');
  const editBtn = document.getElementById(`n-edit-btn-${index}`);
  const saveBtn = document.getElementById(`n-save-btn-${index}`);
  if(editBtn) editBtn.style.display = 'inline-block';
  if(saveBtn) saveBtn.style.display = 'none';
}

window.toggleNutritionEditMode = function(index, event) {
  if (event) event.stopPropagation();
  const wrapper = document.getElementById(`nutri-wrapper-${index}`);
  if (!wrapper.classList.contains('open')) wrapper.classList.add('open');

  document.getElementById(`nutri-hint-${index}`).textContent = 'Düzenleme Modu Açık (İptal için karta tıkla)';

  const views = document.querySelectorAll(`.nutri-view-${index}`);
  const edits = document.querySelectorAll(`.nutri-edit-${index}`);
  views.forEach(el => el.style.display = 'none');
  edits.forEach(el => el.style.display = 'block'); // Kutular ve textarea tam görünsün

  document.getElementById(`n-edit-btn-${index}`).style.display = 'none';
  document.getElementById(`n-save-btn-${index}`).style.display = 'inline-block';
};

window.saveNutritionEdit = async function(index, logDate, event) {
  if (event) event.stopPropagation();
  const username = window._currentUsername;

  const pro = parseFloat(document.getElementById(`n-edit-pro-${index}`).value) || 0;
  const carb = parseFloat(document.getElementById(`n-edit-carb-${index}`).value) || 0;
  const fat = parseFloat(document.getElementById(`n-edit-fat-${index}`).value) || 0;
  const editedDate = document.getElementById(`n-edit-date-${index}`)?.value || logDate;

  const notesInput = document.getElementById(`n-edit-notes-${index}`);
  const notesVal = notesInput ? notesInput.value : '';

  const payload = {
    username: username,
    original_date: logDate,
    log_date: editedDate,
    protein: pro,
    carbs: carb,
    fat: fat,
    calories: Math.round((pro * 4) + (carb * 4) + (fat * 9)),
    notes: notesVal
  };

  try {
    const res = await apiPut('/api/nutrition/log', payload);
    if (res.success) {
      toast('Beslenme kaydı başarıyla güncellendi!', 'success');
      loadNutritionHistory();
    }
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
};

window.deleteNutritionLog = async function(logDate, event) {
  if (event) event.stopPropagation();
  if (!confirm('Bu tarihe ait beslenme verisini silmek istediğinize emin misiniz?')) return;
  const username = window._currentUsername;

  try {
    const res = await apiDelete(`/api/nutrition/log?log_date=${encodeURIComponent(logDate)}`);
    if (res.success) {
      toast('Kayıt silindi!', 'success');
      loadNutritionHistory();
    }
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
};

/* ═══════════════════════════════════════════════
   ANALİZ SAYFASI
═══════════════════════════════════════════════ */
let expertSystemState = null;
let expertPreferenceDraft = { primary_goal: 'hypertrophy', priority_muscles: [] };
let expertCheckinDraft = { session_rpe: null, day_fatigue: null, recovery_feeling: null, completion_percentage: 100 };
let expertDomsDraft = {};

function expertEscape(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char]));
}
function expertToday() { return new Date().toISOString().slice(0, 10); }
function expertDateLabel(value) {
  if (!value) return '—';
  const date = new Date(`${value}T12:00:00`);
  return Number.isNaN(date.getTime()) ? expertEscape(value) : date.toLocaleDateString('tr-TR');
}
function expertGoalLabel(goal) {
  return expertSystemState?.catalog?.primary_goals?.[goal] || goal || '—';
}
function expertScale(field, value) {
  return `<div class="expert-scale">${Array.from({length:11}, (_, number) =>
    `<button type="button" class="${Number(value) === number ? 'selected' : ''}" onclick="expertSetScore('${field}',${number})">${number}</button>`
  ).join('')}</div>`;
}
function expertLoading() {
  const content = document.getElementById('analyzeContent');
  if (content) content.innerHTML = '<div class="card"><p style="color:var(--text-muted);font-size:13px">Uzman sistemi yükleniyor...</p></div>';
}

async function loadExpertSystem() {
  expertLoading();
  try {
    expertSystemState = await apiGet('/api/expert-system');
    if (expertSystemState.preferences) {
      expertPreferenceDraft = {
        primary_goal: expertSystemState.preferences.primary_goal,
        priority_muscles: [...(expertSystemState.preferences.priority_muscles || [])]
      };
    }
    renderExpertSystem();
  } catch (error) {
    const content = document.getElementById('analyzeContent');
    if (content) content.innerHTML = `<div class="card"><p style="color:var(--red)">Uzman sistemi yüklenemedi: ${expertEscape(error.message)}</p></div>`;
  }
}

function expertGateCard(eligibility) {
  const profileMissing = eligibility.reason === 'profile_incomplete';
  const button = profileMissing
    ? `<button class="btn btn-primary" onclick="navigate('profile')">Profil Sayfasına Git</button>`
    : `<button class="btn btn-primary" onclick="navigate('workout')">Antrenman Kaydı Ekle</button>`;
  return `<div class="card expert-card" style="max-width:720px">
    <div class="expert-card-title"><span>Uzman sistemi henüz hazır değil</span><span class="expert-pill warn">Ön koşul gerekli</span></div>
    <p style="margin:0 0 14px;color:var(--text-secondary);font-size:13px;line-height:1.6">${expertEscape(eligibility.message || 'Ön koşulları tamamlayın.')}</p>
    ${profileMissing && eligibility.missing_fields?.length ? `<div class="expert-empty" style="margin-bottom:14px">Eksik profil bilgileri: ${eligibility.missing_fields.map(expertEscape).join(', ')}</div>` : ''}
    ${button}
  </div>`;
}

function expertPreferencesForm() {
  const catalog = expertSystemState?.catalog || { primary_goals: {}, muscle_groups: [] };
  const goals = Object.entries(catalog.primary_goals || {}).map(([key, label]) =>
    `<button type="button" class="expert-choice ${expertPreferenceDraft.primary_goal === key ? 'selected' : ''}" onclick="expertSelectGoal('${key}')">${expertEscape(label)}</button>`
  ).join('');
  const muscles = (catalog.muscle_groups || []).map(group =>
    `<button type="button" class="expert-choice ${expertPreferenceDraft.priority_muscles.includes(group) ? 'selected' : ''}" onclick="expertTogglePriority('${group}')">${expertEscape(group)}</button>`
  ).join('');
  return `<div class="card expert-card">
    <div class="expert-card-title"><span>${expertSystemState?.preferences ? 'Hedeflerini Düzenle' : 'Uzman Sistemi Başlangıç Anketi'}</span><span class="expert-pill">2 kısa tercih</span></div>
    <p style="margin:0 0 16px;color:var(--text-muted);font-size:13px;line-height:1.55">Profilinizde bulunan deneyim, haftalık gün ve seans süresi tekrar sorulmaz. Bu tercihler kaydedilir; daha sonra istediğiniz zaman değiştirebilirsiniz.</p>
    <div style="font-size:12px;font-weight:700;color:var(--text-secondary);margin-bottom:8px">ANA AMAÇ</div>
    <div class="expert-choice-grid" style="margin-bottom:18px">${goals}</div>
    <div style="display:flex;justify-content:space-between;gap:10px;margin-bottom:8px"><span style="font-size:12px;font-weight:700;color:var(--text-secondary)">ÖNCELİKLİ KAS GRUPLARI</span><span style="font-size:11px;color:var(--text-muted)">${expertPreferenceDraft.priority_muscles.length}/3 seçildi</span></div>
    <div class="expert-choice-grid">${muscles}</div>
    <div class="expert-actions" style="margin-top:18px">
      <button class="btn btn-primary" onclick="expertSavePreferences()">Tercihleri Kaydet ve Analizi Aç</button>
      ${expertSystemState?.preferences ? `<button class="btn btn-secondary" onclick="expertClosePanel()">Vazgeç</button>` : ''}
    </div>
  </div>`;
}

function expertResultCard(result) {
  const program = result?.program_focus || {};
  const recovery = result?.recovery || {};
  const score = recovery.recovery_score;
  const scoreColor = score == null ? 'var(--text-muted)' : score < 45 ? 'var(--red)' : score < 70 ? 'var(--orange)' : 'var(--green)';
  const focus = (program.weekly_focus || []).map(item => `<div class="expert-recommendation"><div style="display:flex;justify-content:space-between;gap:10px"><strong>${expertEscape(item.muscle_group)}</strong><span class="expert-pill">${item.recent_direct_sets} set · hedef ${item.recommended_weekly_sets.min}-${item.recommended_weekly_sets.max}</span></div><div style="margin-top:7px;color:var(--text-secondary);font-size:12px;line-height:1.5">${expertEscape(item.message)}</div></div>`).join('') || '<div class="expert-empty">Öncelikli kas seçimi henüz yok.</div>';
  const rules = (recovery.rule_trace || []).map(item => `<li><strong>${expertEscape(item.rule)}:</strong> ${expertEscape(item.detail)}</li>`).join('');
  const doms = (recovery.active_doms || []).map(item => `<span class="expert-pill warn">${expertEscape(item.muscle_group)} ${expertEscape(item.severity)}/10</span>`).join(' ') || '<span style="font-size:12px;color:var(--text-muted)">Aktif DOMS kaydı yok</span>';
  return `<div class="expert-stack">
    <div class="card expert-card">
      <div class="expert-card-title"><span>Bugünkü Karar Desteği</span><span class="expert-pill ${score != null && score >= 70 ? 'good' : score != null ? 'warn' : ''}">${expertEscape(recovery.title || 'Değerlendirme bekleniyor')}</span></div>
      <div style="display:flex;gap:16px;align-items:center"><div style="min-width:78px;text-align:center"><div style="font-size:32px;font-weight:800;color:${scoreColor}">${score == null ? '—' : score}</div><div style="font-size:11px;color:var(--text-muted)">Toparlanma</div></div><div style="font-size:13px;line-height:1.58;color:var(--text-secondary)">${expertEscape(recovery.message || 'Anketi tamamladığınızda değerlendirme burada görünür.')}</div></div>
      <div style="margin-top:14px"><div style="font-size:11px;font-weight:700;color:var(--text-muted);margin-bottom:7px">AKTİF KAS AĞRISI / DOMS</div>${doms}</div>
    </div>
    <div class="card expert-card"><div class="expert-card-title"><span>Hedefe Göre Hacim Odağı</span><span class="expert-pill">${expertEscape(program.primary_goal_label || '—')}</span></div><p style="margin:0;color:var(--text-secondary);font-size:13px;line-height:1.5">${expertEscape(program.message || '')}</p>${focus}</div>
    <div class="card expert-card"><div class="expert-card-title"><span>Neden Bu Öneri?</span><span class="expert-pill">Açıklanabilir kurallar</span></div><ul class="expert-rule-list">${rules}</ul><p style="margin:14px 0 0;color:var(--text-muted);font-size:11px;line-height:1.45">${expertEscape(recovery.disclaimer || '')}</p></div>
  </div>`;
}

function expertActionPanel() {
  const preferences = expertSystemState.preferences;
  const domsCount = (expertSystemState.active_doms || []).length;
  return `<div class="expert-stack">
    <div class="card expert-card"><div class="expert-card-title"><span>Kontrol Anketleri</span><span class="expert-pill good">İsteğe bağlı</span></div>
      <p style="margin:0 0 14px;color:var(--text-muted);font-size:12px;line-height:1.55">Veriler zorunlu günlük bildirim olarak istenmez. Antrenmandan sonra veya toparlanmanızı değerlendirmek istediğiniz günlerde siz başlatırsınız.</p>
      <div class="expert-actions"><button class="btn btn-primary" onclick="expertOpenPanel('session')">Son Seansı Değerlendir</button><button class="btn btn-secondary" onclick="expertOpenPanel('daily')">Günlük Toparlanma Kontrolü</button><button class="btn btn-secondary" onclick="expertOpenPanel('doms')">Kas Ağrısı / DOMS Gir${domsCount ? ` (${domsCount})` : ''}</button></div>
    </div>
    <div class="card expert-card"><div class="expert-card-title"><span>Kaydedilmiş Tercihler</span><button class="btn btn-secondary" style="padding:7px 10px;font-size:12px" onclick="expertOpenPanel('preferences')">Düzenle</button></div><div style="font-size:13px;color:var(--text-secondary);line-height:1.7"><div><span style="color:var(--text-muted)">Amaç:</span> ${expertEscape(expertGoalLabel(preferences.primary_goal))}</div><div><span style="color:var(--text-muted)">Odak:</span> ${expertEscape((preferences.priority_muscles || []).join(', '))}</div></div></div>
    <div id="expertInteractionPanel"></div>
  </div>`;
}

function expertDataPane() {
  if (expertDataTab === 'health') {
    const healthPane = expertDataHealthTab === 'injuries'
      ? expertDataInjuryPane()
      : expertDataDomsPane();
    return `${expertDataHealthTabs()}${healthPane}`;
  }

  if (expertDataTab === 'setup') {
    const setupPane = expertDataSetupTab === 'gyms'
      ? expertDataGymsPane()
      : expertDataGoalsPane();
    return `${expertDataSetupTabs()}${setupPane}`;
  }

  const planningPane = expertDataPlanningTab === 'analysis'
    ? expertDataAnalysisDraftPane()
    : expertDataSplitDraftPane();
  return `${expertDataPlanningTabs()}${planningPane}`;
}

function renderExpertSystem() {
  const content = document.getElementById('analyzeContent');
  if (!content || !expertSystemState) return;
  const eligibility = expertSystemState.eligibility || {};
  if (!eligibility.ready) { content.innerHTML = expertGateCard(eligibility); return; }
  if (!expertSystemState.preferences) { content.innerHTML = expertPreferencesForm(); return; }
  content.innerHTML = `<div class="expert-layout"><div>${expertResultCard(expertSystemState.result)}</div><div>${expertActionPanel()}</div></div>`;
}

window.expertSelectGoal = function(goal) { expertPreferenceDraft.primary_goal = goal; const panel = document.getElementById('expertInteractionPanel'); if (panel) panel.innerHTML = expertPreferencesForm(); else renderExpertSystem(); };
window.expertTogglePriority = function(group) {
  const selected = expertPreferenceDraft.priority_muscles;
  if (selected.includes(group)) expertPreferenceDraft.priority_muscles = selected.filter(item => item !== group);
  else if (selected.length >= 3) { toast('En fazla 3 öncelikli kas grubu seçebilirsiniz.', 'error'); return; }
  else expertPreferenceDraft.priority_muscles = [...selected, group];
  const panel = document.getElementById('expertInteractionPanel'); if (panel) panel.innerHTML = expertPreferencesForm(); else renderExpertSystem();
};
window.expertSavePreferences = async function() {
  try {
    const state = await apiPost('/api/expert-system/preferences', expertPreferenceDraft);
    expertSystemState = state;
    toast('Uzman sistemi tercihleri kaydedildi.', 'success');
    renderExpertSystem();
  } catch (error) { toast(error.message, 'error'); }
};
window.expertClosePanel = function() { const panel = document.getElementById('expertInteractionPanel'); if (panel) panel.innerHTML = ''; };
window.expertSetScore = function(field, score) {
  expertCheckinDraft[field] = score;
  const panel = document.getElementById('expertInteractionPanel');
  if (panel) panel.innerHTML = expertCheckinForm(window._expertPanelType || 'session');
};

function expertCheckinForm(type) {
  const session = type === 'session';
  const title = session ? 'Son Seansı Değerlendir' : 'Günlük Toparlanma Kontrolü';
  const rpe = session ? `<div class="wide"><label>Son seansın genel zorluğu — RPE (0–10)</label>${expertScale('session_rpe', expertCheckinDraft.session_rpe)}<div style="font-size:11px;color:var(--text-muted);margin-top:5px">0: çok kolay · 10: maksimum efor</div></div>` : '';
  const completion = session ? `<div><label>Planlanan setleri tamamlama (%)</label><input type="number" id="expertCompletion" min="0" max="100" value="${expertCheckinDraft.completion_percentage ?? 100}" /></div>` : '';
  return `<div class="card expert-card" style="margin-top:16px"><div class="expert-card-title"><span>${title}</span><button class="btn btn-secondary" style="padding:6px 9px;font-size:12px" onclick="expertClosePanel()">Kapat</button></div><div class="expert-form-grid">${rpe}<div class="wide"><label>Gün içindeki yorgunluk (0–10)</label>${expertScale('day_fatigue', expertCheckinDraft.day_fatigue)}</div><div class="wide"><label>Ne kadar toparlanmış hissediyorsun? (0–10)</label>${expertScale('recovery_feeling', expertCheckinDraft.recovery_feeling)}</div>${completion}<div><label>Tarih</label><input type="date" id="expertCheckinDate" value="${expertToday()}" /></div><div class="wide"><label>Kısa not (isteğe bağlı)</label><textarea id="expertCheckinNotes" rows="2" maxlength="1000" placeholder="Uyku, stres, performans veya dikkat çeken durumlar..."></textarea></div></div><div class="expert-actions" style="margin-top:16px"><button class="btn btn-primary" onclick="expertSubmitCheckin('${type}')">Değerlendirmeyi Kaydet</button></div></div>`;
}

function expertDomsForm() {
  const groups = expertSystemState.catalog?.muscle_groups || [];
  const active = Object.fromEntries((expertSystemState.active_doms || []).map(item => [item.muscle_group, Number(item.last_severity || 0)]));
  if (!Object.keys(expertDomsDraft).length) expertDomsDraft = { ...active };
  const rows = groups.map(group => {
    const score = Number(expertDomsDraft[group] ?? active[group] ?? 0);
    return `<div class="expert-doms-row"><div class="expert-doms-name">${expertEscape(group)}</div><input type="range" min="0" max="10" step="1" value="${score}" oninput="expertSetDoms('${group}', this.value)" /><div class="expert-doms-score" id="expertDomsScore_${group}">${score}/10</div></div>`;
  }).join('');
  return `<div class="card expert-card" style="margin-top:16px"><div class="expert-card-title"><span>Kas Ağrısı / DOMS Takibi</span><button class="btn btn-secondary" style="padding:6px 9px;font-size:12px" onclick="expertClosePanel()">Kapat</button></div><p style="margin:0 0 10px;font-size:12px;color:var(--text-muted);line-height:1.55">Ağrı başlayan kaslar için şiddeti girin. Aktif bir ağrı 0'a indiğinde kayıt kapanır. Keskin, olağandışı ya da günlük yaşamı etkileyen ağrı için antrenmanı bırakıp sağlık uzmanına başvurun.</p>${rows}<div class="expert-form-grid" style="margin-top:12px"><div><label>Tarih</label><input type="date" id="expertDomsDate" value="${expertToday()}" /></div></div><div class="expert-actions" style="margin-top:16px"><button class="btn btn-primary" onclick="expertSubmitDoms()">DOMS Durumunu Kaydet</button></div></div>`;
}

window.expertOpenPanel = function(type) {
  window._expertPanelType = type;
  const panel = document.getElementById('expertInteractionPanel');
  if (!panel) return;
  if (type === 'preferences') { expertPreferenceDraft = { primary_goal: expertSystemState.preferences.primary_goal, priority_muscles: [...(expertSystemState.preferences.priority_muscles || [])] }; panel.innerHTML = expertPreferencesForm(); return; }
  if (type === 'doms') { expertDomsDraft = {}; panel.innerHTML = expertDomsForm(); return; }
  expertCheckinDraft = { session_rpe: null, day_fatigue: null, recovery_feeling: null, completion_percentage: 100 };
  panel.innerHTML = expertCheckinForm(type);
};
window.expertSetDoms = function(group, value) { expertDomsDraft[group] = Number(value); const item = document.getElementById(`expertDomsScore_${group}`); if (item) item.textContent = `${value}/10`; };
window.expertSubmitCheckin = async function(type) {
  const completion = type === 'session' ? Number(document.getElementById('expertCompletion')?.value) : null;
  const payload = { checkin_type:type, checkin_date:document.getElementById('expertCheckinDate')?.value, session_rpe:type === 'session' ? expertCheckinDraft.session_rpe : null, day_fatigue:expertCheckinDraft.day_fatigue, recovery_feeling:expertCheckinDraft.recovery_feeling, completion_percentage:completion, notes:document.getElementById('expertCheckinNotes')?.value || '' };
  try { expertSystemState = await apiPost('/api/expert-system/checkins', payload); toast('Toparlanma değerlendirmesi kaydedildi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); }
};
window.expertSubmitDoms = async function() {
  const active = new Set((expertSystemState.active_doms || []).map(item => item.muscle_group));
  const reports = Object.entries(expertDomsDraft).filter(([group, value]) => Number(value) > 0 || active.has(group)).map(([muscle_group, severity]) => ({ muscle_group, severity:Number(severity) }));
  if (!reports.length) { toast('Kaydedilecek bir aktif DOMS kaydı yok. Ağrı hissettiğiniz kasın değerini 0 üzerinde seçin.', 'error'); return; }
  try { expertSystemState = await apiPost('/api/expert-system/doms-reports', { report_date:document.getElementById('expertDomsDate')?.value, reports }); toast('DOMS kayıtları güncellendi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); }
};

function onAnalyzePageEnter() { loadExpertSystem(); }

/* ═══════════════════════════════════════════════
   İLERLEME (PROGRESS) SAYFASI
═══════════════════════════════════════════════ */

let _exerciseProgressChart = null; // Yeni dinamik egzersiz grafiği için
let exercisePool = [];             // Arama menüsü için
// İlk sayfa yüklemesinde zamanlama hatasını önlemek için bu durumlar erken başlatılır.
let _progRawData = null;
let _progHistoricalRecords = [];
let _progExercise = '';
let _progTimeframe = 'monthly';
let _progChartMode = 'weight';

// 1. İlerleme Sayfası Yüklendiğinde
async function loadProgress(username) {
  // ── A: GENEL VERİLER (PR Tablosu ve Eski Grafik) ──
  try {
    const data = await apiGet(`/api/progress`);

    // Havuzda artık olmayan eski/özel hareketler de arama listesine eklenir.
    _progHistoricalRecords = Array.isArray(data.personal_records) ? data.personal_records : [];

    // Eski Hacim Grafiği
    const ctx1El = document.getElementById('progressChart');
    if (ctx1El && data.volume_timeline) {
      if (_progressChart) _progressChart.destroy();
      _progressChart = new Chart(ctx1El.getContext('2d'), {
        type: 'line',
        data: {
          labels: data.volume_timeline.map(v => v.date),
          datasets: [{ label: 'Hacim (kg)', data: data.volume_timeline.map(v => v.volume), borderColor: '#6c63ff', backgroundColor: 'rgba(108,99,255,0.1)', fill: true, tension: 0.4 }]
        },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true }, x: { grid: { display: false } } } }
      });
    }

    // 🏆 PR (PERSONAL RECORDS) TABLOSU - TEK PARÇA KUSURSUZ KOD
    // Yeni Egzersiz İlerleme Grafiği — varsayılan hareket: en üstteki PR, yoksa havuzdan ilk
    let defaultExercise = null;
    let defaultExerciseName = '';
    if (data.personal_records && data.personal_records.length > 0) {
      defaultExercise = data.personal_records[0].exercise_id || data.personal_records[0].exercise;
      defaultExerciseName = data.personal_records[0].exercise || '';
    } else if (_exercisePool && _exercisePool.length > 0) {
      defaultExercise = _exercisePool[0].name;
    }
    if (defaultExercise) {
      await selectProgressExercise(defaultExercise, defaultExerciseName);
    } else {
      renderExerciseProgressChart('', { labels: [], data: [], details: [] });
    }

    const prs = data.personal_records || [];
    const prTable = document.getElementById('prTable');

    if (prTable) {
      if (!prs || prs.length === 0) {
        prTable.innerHTML = '<tr><td colspan="5" style="text-align:center; color:rgba(255,255,255,0.7); padding:24px;">Henüz PR verisi bulunmuyor</td></tr>';
      } else {
        const COMPOUND_KEYWORDS = ['bench', 'squat', 'deadlift', 'Overhead Press', 'barbell row', 'bulgarian'];
        const compoundPRs = [];
        const muscleGroupPRs = {};


        // Tarih Formatlayıcı
        const formatDateTr = (dateStr) => {
          if (!dateStr) return "-";
          const parts = dateStr.split(" ")[0].split("-");
          if (parts.length === 3) return `${parts[2]}.${parts[1]}.${parts[0]}`;
          return dateStr;
        };

        prs.forEach(r => {
          const exName = (r.exercise || "").toLowerCase();
          const isCompound = COMPOUND_KEYWORDS.some(k => exName.includes(k));

          r.formattedDate = formatDateTr(r.date);

          if (isCompound) {
            compoundPRs.push(r);
          } else {
            const muscle = r.muscle || "Diğer";
            let mainGroup = "Diğer";

            if (muscle === "Göğüs") mainGroup = "Göğüs";
            else if (muscle === "Sırt") mainGroup = "Sırt";
            else if (["Biceps", "Triceps"].includes(muscle)) mainGroup = "Kol";
            // Bacak yalnız üst sunum grubudur; satırdaki gerçek kas rozeti korunur.
            else if (["Bacak", "Legs", "Leg", "Alt Vücut", "Quadriceps", "Hamstring", "Glute", "Gluteus", "Calf", "Adductors"].includes(muscle)) mainGroup = "Bacak";
            else if (muscle === "Omuz") mainGroup = "Omuz";
            else if (muscle === "Core") mainGroup = "Core";
            else mainGroup = "Diğer";

            if (!muscleGroupPRs[mainGroup]) {
              muscleGroupPRs[mainGroup] = [];
            }
            muscleGroupPRs[mainGroup].push(r);
          }
        });

        //  TEMA VE ROZET AYARLARI
        const MUSCLE_THEMES = {
          "Göğüs": {
            bg: "linear-gradient(90deg, rgba(59, 130, 246, 0.22) 0%, rgba(6, 182, 212, 0.05) 100%)",
            border: "#3b82f6", text: "#60a5fa",
            badge: "background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Sırt": {
            bg: "linear-gradient(90deg, rgba(34, 197, 94, 0.22) 0%, rgba(16, 185, 129, 0.05) 100%)",
            border: "#22c55e", text: "#4ade80",
            badge: "background: rgba(34, 197, 94, 0.15); color: #4ade80; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Omuz": {
            bg: "linear-gradient(90deg, rgba(168, 85, 247, 0.22) 0%, rgba(236, 72, 153, 0.05) 100%)",
            border: "#a855f7", text: "#c084fc",
            badge: "background: rgba(168, 85, 247, 0.15); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Kol": {
            bg: "linear-gradient(90deg, rgba(245, 158, 11, 0.22) 0%, rgba(249, 115, 22, 0.05) 100%)",
            border: "#f59e0b", text: "#fbbf24",
            badge: "background: rgba(245, 158, 11, 0.15); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Bacak": {
            bg: "linear-gradient(90deg, rgba(239, 68, 68, 0.22) 0%, rgba(244, 63, 94, 0.05) 100%)",
            border: "#ef4444", text: "#f87171",
            badge: "background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Quadriceps": {
            bg: "linear-gradient(90deg, rgba(239, 68, 68, 0.22) 0%, rgba(244, 63, 94, 0.05) 100%)",
            border: "#ef4444", text: "#f87171",
            badge: "background: rgba(239, 68, 68, 0.15); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Hamstring": {
            bg: "linear-gradient(90deg, rgba(244, 63, 94, 0.22) 0%, rgba(251, 113, 133, 0.05) 100%)",
            border: "#f43f5e", text: "#fda4af",
            badge: "background: rgba(244, 63, 94, 0.15); color: #fda4af; border: 1px solid rgba(244, 63, 94, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Gluteus": {
            bg: "linear-gradient(90deg, rgba(249, 115, 22, 0.22) 0%, rgba(251, 146, 60, 0.05) 100%)",
            border: "#f97316", text: "#fdba74",
            badge: "background: rgba(249, 115, 22, 0.15); color: #fdba74; border: 1px solid rgba(249, 115, 22, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Calf": {
            bg: "linear-gradient(90deg, rgba(236, 72, 153, 0.22) 0%, rgba(244, 114, 182, 0.05) 100%)",
            border: "#ec4899", text: "#f9a8d4",
            badge: "background: rgba(236, 72, 153, 0.15); color: #f9a8d4; border: 1px solid rgba(236, 72, 153, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Adductors": {
            bg: "linear-gradient(90deg, rgba(217, 70, 239, 0.22) 0%, rgba(232, 121, 249, 0.05) 100%)",
            border: "#d946ef", text: "#f0abfc",
            badge: "background: rgba(217, 70, 239, 0.15); color: #f0abfc; border: 1px solid rgba(217, 70, 239, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "Core": {
            bg: "linear-gradient(90deg, rgba(20, 184, 166, 0.22) 0%, rgba(6, 182, 212, 0.05) 100%)",
            border: "#14b8a6", text: "#2dd4bf",
            badge: "background: rgba(20, 184, 166, 0.15); color: #2dd4bf; border: 1px solid rgba(20, 184, 166, 0.3); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          },
          "DEFAULT": {
            bg: "linear-gradient(90deg, rgba(148, 163, 184, 0.18) 0%, rgba(203, 213, 225, 0.03) 100%)",
            border: "#94a3b8", text: "#cbd5e1",
            badge: "background: rgba(255, 255, 255, 0.1); color: #ffffff; border: 1px solid rgba(255, 255, 255, 0.2); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; display: inline-block;"
          }
        };

        const getThemeForMuscle = (muscleName) => {
            if (["Biceps", "Triceps"].includes(muscleName)) return MUSCLE_THEMES["Kol"];
            if (["Bacak", "Legs", "Leg", "Alt Vücut"].includes(muscleName)) return MUSCLE_THEMES["Bacak"];
            return MUSCLE_THEMES[muscleName] || MUSCLE_THEMES["DEFAULT"];
        };

        const weightColor = "#ffffff";
        const repsColor = "rgba(255, 255, 255, 0.95)";
        const dateColor = "rgba(255, 255, 255, 0.95)";

        let tableHTML = '';

        // 1. BİLEŞİK HAREKETLER
        if (compoundPRs.length > 0) {
          tableHTML += `
            <tr style="background: linear-gradient(90deg, rgba(108, 99, 255, 0.28) 0%, rgba(217, 70, 239, 0.12) 100%); border-left: 4px solid var(--accent);">
              <td colspan="5" style="padding: 11px 16px; font-weight: 900; font-size: 13px; color: #ffffff; letter-spacing: 0.8px; text-transform: uppercase;">
                BİLEŞİK HAREKETLER (COMPOUND)
              </td>
            </tr>
          `;

          compoundPRs.forEach(r => {
            const compBadge = `background: linear-gradient(90deg, rgba(108, 99, 255, 0.2) 0%, rgba(217, 70, 239, 0.05) 100%); color: #c084fc; border: 1px solid rgba(108, 99, 255, 0.4); padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; display: inline-block;`;
            tableHTML += `
              <tr style="transition: all 0.2s; border-bottom: 1px solid rgba(255,255,255,0.05);" onmouseover="this.style.background='rgba(255, 255, 255, 0.05)'" onmouseout="this.style.background='transparent'">
                <td style="padding: 12px 16px; font-weight: 600; color: #ffffff; font-size: 13px;">${r.exercise}</td>
                <td><span style="${compBadge}">${r.muscle}</span></td>
                <td style="font-weight: 800; color: ${weightColor}; font-size: 14px;">${r.max_weight} kg</td>
                <td><span style="font-size: 12px; color: ${repsColor}; font-weight: 600;">${r.max_reps} Tekrar</span></td>
                <td style="font-size: 12px; color: ${dateColor};">${r.formattedDate}</td>
              </tr>
            `;
          });
        }

        // 2. BÖLGESEL HAREKETLER
        const groupOrder = ["Göğüs", "Sırt", "Omuz", "Kol", "Bacak", "Core", "Diğer"];
        const existingGroups = Object.keys(muscleGroupPRs).sort((a, b) => {
          let idxA = groupOrder.indexOf(a);
          let idxB = groupOrder.indexOf(b);
          if (idxA === -1) idxA = 99;
          if (idxB === -1) idxB = 99;
          return idxA - idxB;
        });

        existingGroups.forEach(mainGroup => {
          const groupPRs = muscleGroupPRs[mainGroup];
          const theme = MUSCLE_THEMES[mainGroup] || MUSCLE_THEMES["DEFAULT"];

          groupPRs.sort((a, b) => a.muscle.localeCompare(b.muscle, 'tr-TR'));

          tableHTML += `
            <tr style="background: ${theme.bg}; border-left: 4px solid ${theme.border};">
              <td colspan="5" style="padding: 10px 16px; font-weight: 800; font-size: 12px; color: ${theme.text}; letter-spacing: 0.6px; text-transform: uppercase;">
                 ${mainGroup} HAREKETLERİ
              </td>
            </tr>
          `;

          groupPRs.forEach(r => {
            tableHTML += `
              <tr style="transition: all 0.2s; border-bottom: 1px solid rgba(255,255,255,0.05);" onmouseover="this.style.background='rgba(255, 255, 255, 0.05)'" onmouseout="this.style.background='transparent'">
                <td style="padding: 12px 16px 12px 24px; font-weight: 500; color: #ffffff; font-size: 13px;">${r.exercise}</td>
                <td><span style="${getThemeForMuscle(r.muscle).badge}">${r.muscle}</span></td>
                <td style="font-weight: 700; color: ${weightColor}; font-size: 13px;">${r.max_weight} kg</td>
                <td><span style="font-size: 12px; color: ${repsColor}; font-weight: 500;">${r.max_reps} Tekrar</span></td>
                <td style="font-size: 12px; color: ${dateColor};">${r.formattedDate}</td>
              </tr>
            `;
          });
        });

        prTable.innerHTML = tableHTML;
      }
    }
  } catch (e) {
    console.error("Genel ilerleme (PR) verileri çekilirken hata:", e);
  }

  // ── B: YENİ EGZERSİZ ZAMAN SERİSİ (Arama Menüsü İçin) ──
  try {
    const exData = await apiGet('/api/exercises');
    _exercisePool = exData.exercises || [];
    buildExerciseDropdown(); // Dropdown'ı hazırla
  } catch(e) {
    console.warn("Egzersiz havuzu çekilemedi, arama menüsü boş kalabilir.");
  }

  // Dışarı tıklandığında dropdown'ı kapatma olayı
  document.addEventListener('click', function(e) {
    const input = document.getElementById('exerciseSearchInput');
    const dropdown = document.getElementById('exerciseDropdownList');
    if (input && dropdown && !input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = 'none';
    }
  });

  // Varsayılan hareketi, mevcut seçim varsa koruyarak yükle.
  const selectedExercise = document.getElementById('exerciseSearchInput')?.value?.trim() || 'Bench Press';
  selectProgressExercise(selectedExercise);
}

/* ═══════════════════════════════════════════════
   YENİ GRAFİK: ARAMA VE ÇİZİM FONKSİYONLARI
═══════════════════════════════════════════════ */

// 1. Egzersiz Seçim Fonksiyonu (Hem normal hem de window kapsamına tanımlıyoruz)
async function selectProgressExercise(exerciseRef, displayName = '') {
  const selected = (_exercisePool || []).find(item => item.id === exerciseRef || item.name === exerciseRef);
  const exerciseId = selected?.id || exerciseRef;
  const exerciseName = displayName || selected?.name || String(exerciseRef || '');
  const inputEl = document.getElementById('exerciseSearchInput');
  if (inputEl) inputEl.value = exerciseName;
  const dropdownEl = document.getElementById('exerciseDropdownList');
  if (dropdownEl) dropdownEl.style.display = 'none';
  try {
    const response = await apiGet('/api/progress/chart?exercise_id=' + encodeURIComponent(exerciseId));
    renderExerciseProgressChart(response.exercise_name || exerciseName, response);
  } catch (error) {
    console.error('Grafik verisi çekilirken API hatası:', error);
    renderExerciseProgressChart(exerciseName, { labels: [], data: [], details: [], metric_type: 'weight_kg', metric_label: 'PR ağırlık (kg)' });
  }
}

// Inline HTML erişebilsin diye explicitly window objesine bağlıyoruz
window.selectProgressExercise = selectProgressExercise;


// 2. Dropdown Menüyü Oluşturma
function _progressMuscleGroup(exercise) {
  const raw = String(exercise?.muscle || exercise?.muscle_group || 'Diğer').trim();
  const aliases = {
    'Chest': 'Göğüs', 'Göğüs': 'Göğüs',
    'Back': 'Sırt', 'Sırt': 'Sırt',
    'Shoulders': 'Omuz', 'Shoulder': 'Omuz', 'Omuz': 'Omuz',
    'Biceps': 'Kol', 'Triceps': 'Kol', 'Arms': 'Kol', 'Arm': 'Kol', 'Kol': 'Kol',
    // Bacak yalnız seçim listesinin üst sunum grubudur; gerçek kas bilgisi kayıtta korunur.
    'Legs': 'Bacak', 'Leg': 'Bacak', 'Bacak': 'Bacak', 'Alt Vücut': 'Bacak',
    'Quadriceps': 'Bacak', 'Hamstring': 'Bacak', 'Glute': 'Bacak', 'Gluteus': 'Bacak',
    'Calf': 'Bacak', 'Adductors': 'Bacak',
    'Rotatorlar': 'Rotatorlar', 'Rotator Cuff': 'Rotatorlar', 'Hip Rotators': 'Rotatorlar',
    'Core': 'Core', 'Abs': 'Core', 'Karın': 'Core'
  };
  return aliases[raw] || raw || 'Diğer';
}

function _escapeProgressHtml(value) {
  return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function buildExerciseDropdown(filterText = '') {
  const dropdown = document.getElementById('exerciseDropdownList');
  if (!dropdown) return;

  const search = String(filterText || '').trim().toLocaleLowerCase('tr-TR');
  const groupOrder = ['Göğüs', 'Sırt', 'Omuz', 'Kol', 'Bacak', 'Rotatorlar', 'Core', 'Diğer'];
  const grouped = new Map();

  const selectableExercises = [...(_exercisePool || [])];
  // Güncel havuzda karşılığı olmayan eski/özel hareketler de seçilebilir
  // kalsın; id'si legacy: ile başladığı için backend onları tarihsel akışta arar.
  (_progHistoricalRecords || []).forEach(record => {
    const legacyId = String(record?.exercise_id || '');
    if (!legacyId.startsWith('legacy:')) return;
    if (selectableExercises.some(item => String(item.id) === legacyId)) return;
    selectableExercises.push({
      id: legacyId,
      name: String(record.exercise || 'Eski hareket'),
      muscle: record.muscle || 'Diğer',
      is_legacy_exercise: true
    });
  });

  selectableExercises.forEach(exercise => {
    const name = String(exercise?.name || '');
    if (!name || (search && !name.toLocaleLowerCase('tr-TR').includes(search))) return;
    const group = _progressMuscleGroup(exercise);
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push(exercise);
  });

  const groups = [...grouped.keys()].sort((a, b) => {
    const aOrder = groupOrder.indexOf(a); const bOrder = groupOrder.indexOf(b);
    return (aOrder < 0 ? 99 : aOrder) - (bOrder < 0 ? 99 : bOrder) || a.localeCompare(b, 'tr-TR');
  });

  let html = '';
  groups.forEach(group => {
    const exercises = grouped.get(group).sort((a, b) => String(a.name).localeCompare(String(b.name), 'tr-TR'));
    html += `<div class="dropdown-group-header">${_escapeProgressHtml(group)}</div>`;
    exercises.forEach(exercise => {
      const encodedId = encodeURIComponent(String(exercise.id));
      const encodedName = encodeURIComponent(String(exercise.name));
      html += `<button type="button" class="dropdown-item-option" onmousedown="event.preventDefault(); window.selectProgressExercise(decodeURIComponent('${encodedId}'), decodeURIComponent('${encodedName}'))">${_escapeProgressHtml(exercise.name)}</button>`;
    });
  });

  dropdown.innerHTML = html || `<div style="padding: 12px; font-size: 12px; color: var(--text-muted); text-align: center;">Eşleşen egzersiz bulunamadı</div>`;
}

window.buildExerciseDropdown = buildExerciseDropdown;


// 3. HTML Input Olayları
window.showExerciseDropdown = function() {
  const input = document.getElementById('exerciseSearchInput');
  const dropdown = document.getElementById('exerciseDropdownList');
  if (!dropdown) return;
  buildExerciseDropdown(input?.value || '');
  dropdown.style.display = 'block';
};

window.filterExerciseDropdown = function(value) {
  const dropdown = document.getElementById('exerciseDropdownList');
  if (!dropdown) return;
  buildExerciseDropdown(value || '');
  dropdown.style.display = 'block';
};

/* ═══════════════════════════════════════════════════════════════════
   GRAFİK HÜZME DOLUM ANİMASYONU
   Her yeni Chart örneğinde grafik alanı aşağıdan yukarı açılır; hareket,
   metrik veya dönem değiştiğinde grafik yeniden oluşturulduğu için efekt
   tekrar tetiklenir.
═══════════════════════════════════════════════════════════════════ */
function _hxColorWithAlpha(hex, alpha) {
  const value = String(hex || '#6c63ff').replace('#', '').trim();
  const full = value.length === 3 ? value.split('').map(c => c + c).join('') : value;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return `rgba(108, 99, 255, ${alpha})`;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const _hxBeamRevealPlugin = {
  id: 'hxBeamReveal',
  beforeDatasetsDraw(chart) {
    const state = chart.$hxBeam;
    const area = chart.chartArea;
    if (!state || !area || state.progress >= 1) return;
    const revealTop = area.bottom - ((area.bottom - area.top) * state.progress);
    chart.ctx.save();
    chart.ctx.beginPath();
    chart.ctx.rect(area.left - 2, revealTop, (area.right - area.left) + 4, (area.bottom - revealTop) + 2);
    chart.ctx.clip();
    state.isClipped = true;
  },
  afterDatasetsDraw(chart) {
    const state = chart.$hxBeam;
    const area = chart.chartArea;
    if (!state || !area || state.progress >= 1) return;
    if (state.isClipped) {
      chart.ctx.restore();
      state.isClipped = false;
    }
    const revealY = area.bottom - ((area.bottom - area.top) * state.progress);
    const ctx = chart.ctx;
    ctx.save();
    ctx.beginPath();
    ctx.rect(area.left, area.top, area.right - area.left, area.bottom - area.top);
    ctx.clip();
    const glow = ctx.createLinearGradient(0, revealY - 46, 0, revealY + 46);
    glow.addColorStop(0, _hxColorWithAlpha(state.color, 0));
    glow.addColorStop(0.36, _hxColorWithAlpha(state.color, 0.06));
    glow.addColorStop(0.50, _hxColorWithAlpha(state.color, 0.42));
    glow.addColorStop(0.64, _hxColorWithAlpha(state.color, 0.08));
    glow.addColorStop(1, _hxColorWithAlpha(state.color, 0));
    ctx.fillStyle = glow;
    ctx.fillRect(area.left, revealY - 46, area.right - area.left, 92);
    ctx.restore();
  },
  afterDraw(chart) {
    const state = chart.$hxBeam;
    if (state?.isClipped) {
      chart.ctx.restore();
      state.isClipped = false;
    }
  }
};

function _registerHxBeamPlugin() {
  if (typeof Chart === 'undefined') return;
  try {
    if (!Chart.registry.plugins.get('hxBeamReveal')) Chart.register(_hxBeamRevealPlugin);
  } catch (error) {
    try { Chart.register(_hxBeamRevealPlugin); } catch (_) { /* kayıt zaten yapılmış olabilir */ }
  }
}

function _hxChartAnimation() {
  return { duration: 820, easing: 'easeOutQuart' };
}

function _playHxBeamReveal(chart, color) {
  if (!chart) return;
  _registerHxBeamPlugin();
  chart.$hxBeam = { progress: 0, color: color || '#6c63ff', isClipped: false };
  const start = performance.now();
  const duration = 820;
  const animate = (now) => {
    if (!chart || !chart.ctx) return;
    const raw = Math.min(1, (now - start) / duration);
    chart.$hxBeam.progress = 1 - Math.pow(1 - raw, 3);
    chart.draw();
    if (raw < 1) requestAnimationFrame(animate);
    else {
      chart.$hxBeam.progress = 1;
      chart.draw();
    }
  };
  requestAnimationFrame(animate);
}

/* ═══════════════════════════════════════════════════════════════════
   İLERLEME — EGZERSİZ GRAFİK MOTORU (AYLIK / YILLIK / GENEL)
   Aynı gün birden fazla set varsa: çizgiye o günün PR'sı (en yüksek
   ağırlık) işlenir; tüm setler hover tooltip'inde gösterilir.
═══════════════════════════════════════════════════════════════════ */
// Grafik durumları İLERLEME bölümü başında başlatılır.

function _progParseDate(trLabel) {
  if (!trLabel || trLabel === 'Veri Yok') return null;
  const parts = trLabel.split('.');
  if (parts.length !== 3) return null;
  return new Date(Number(parts[2]), Number(parts[1]) - 1, Number(parts[0]));
}

function switchProgTimeframe(tf) {
  _progTimeframe = tf;
  ['monthly', 'yearly', 'all'].forEach(t => {
    const el = document.getElementById('progTime_' + t);
    if (el) el.classList.toggle('active', t === tf);
  });
  renderExerciseProgressChart(_progExercise, null);
}
window.switchProgTimeframe = switchProgTimeframe;

function switchProgChartMode(mode) {
  if (!['weight', 'reps_weight'].includes(mode)) return;
  _progChartMode = mode;
  ['weight', 'reps_weight'].forEach(item => {
    const el = document.getElementById('progView_' + item);
    if (el) el.classList.toggle('active', item === mode);
  });
  const subtitle = document.getElementById('progressChartSubtitle');
  if (subtitle) {
    subtitle.textContent = mode === 'reps_weight'
      ? 'Her antrenman tarihinde en ağır setin ağırlığı ve o ağırlıktaki en yüksek tekrar'
      : 'Seçilen hareketin zaman içindeki kaldırdığı ağırlık değişimi — PR çizgisi ve set detayları';
  }
  renderExerciseProgressChart(_progExercise, null);
}
window.switchProgChartMode = switchProgChartMode;

function _progFilteredPoints() {
  if (!_progRawData?.labels?.length) return [];
  const now = new Date();
  let cutoff = null;
  if (_progTimeframe === 'monthly') { const d = new Date(now); d.setMonth(d.getMonth() - 1); cutoff = d; }
  else if (_progTimeframe === 'yearly') { const d = new Date(now); d.setFullYear(d.getFullYear() - 1); cutoff = d; }
  return _progRawData.labels.map((label, index) => {
    const detail = _progRawData.details[index] || {};
    return {
      label,
      iso: _progParseDate(label),
      value: Number(_progRawData.data[index] || 0),
      reps: Number(detail.reps || 0),
      weightKg: Number(detail.weight_kg || 0),
      set: Number(detail.set || index + 1)
    };
  }).filter(point => point.iso && (!cutoff || point.iso >= cutoff));
}

function renderExerciseProgressChart(exName, raw) {
  if (typeof Chart === 'undefined') {
    console.error('HATA: Chart.js kütüphanesi yüklenmedi!');
    return;
  }
  const ctxEl = document.getElementById('exerciseProgressChart');
  if (!ctxEl) return;
  _registerHxBeamPlugin();
  const ctx = ctxEl.getContext('2d');
  if (_exerciseProgressChart) _exerciseProgressChart.destroy();
  if (raw) {
    _progRawData = { labels: raw.labels || [], data: raw.data || [], details: raw.details || [], metric_type: raw.metric_type || 'weight_kg', metric_label: raw.metric_label || 'PR ağırlık (kg)' };
    _progExercise = exName;
  }

  const metricType = _progRawData?.metric_type || 'weight_kg';
  const metricLabel = _progRawData?.metric_label || 'PR ağırlık (kg)';
  const metricSuffix = metricType === 'reps' ? ' tekrar' : ' kg';
  const points = _progFilteredPoints();
  const isRepsWeightMode = _progChartMode === 'reps_weight';

  if (isRepsWeightMode) {
    // Aynı antrenman günündeki setleri tek bir performans özetine indirgeriz:
    // en yüksek ağırlık ve o ağırlıktaki en yüksek tekrar. Böylece x ekseni
    // her zaman tarihtir; kullanıcı hem yük hem tekrar trendini birlikte okur.
    const groups = new Map();
    for (const point of points.filter(point => point.reps > 0 && point.weightKg > 0)) {
      const key = point.iso.toISOString().split('T')[0];
      if (!groups.has(key)) groups.set(key, { dateIso: key, tr: point.label, sets: [] });
      groups.get(key).sets.push(point);
    }
    const labels = [];
    const daySummaries = [];
    for (const group of [...groups.values()].sort((a, b) => a.dateIso.localeCompare(b.dateIso))) {
      const maxWeight = Math.max(...group.sets.map(set => set.weightKg));
      const repsAtMaxWeight = Math.max(...group.sets
        .filter(set => set.weightKg === maxWeight)
        .map(set => set.reps));
      labels.push(group.tr);
      daySummaries.push({ ...group, maxWeight, repsAtMaxWeight });
    }
    const hasData = daySummaries.length > 0;
    _exerciseProgressChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: hasData ? labels : ['Veri Yok'],
        datasets: [
          {
            label: 'En ağır set — Ağırlık (kg)',
            data: hasData ? daySummaries.map(day => day.maxWeight) : [0],
            yAxisID: 'yWeight',
            borderColor: '#6c63ff',
            backgroundColor: 'rgba(108, 99, 255, 0.14)',
            borderWidth: 3,
            fill: true,
            tension: 0.28,
            pointBackgroundColor: '#6c63ff',
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
            pointRadius: 6,
            pointHoverRadius: 9,
          },
          {
            label: 'En ağır sette — Tekrar',
            data: hasData ? daySummaries.map(day => day.repsAtMaxWeight) : [0],
            yAxisID: 'yReps',
            borderColor: '#22c55e',
            backgroundColor: 'rgba(34, 197, 94, 0.14)',
            borderWidth: 3,
            fill: false,
            tension: 0.28,
            pointBackgroundColor: '#22c55e',
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
            pointRadius: 6,
            pointHoverRadius: 9,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: _hxChartAnimation(),
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: hasData,
            position: 'bottom',
            labels: { color: '#c8cad8', usePointStyle: true, boxWidth: 9, padding: 16 },
          },
          title: {
            display: !hasData,
            text: 'Bu zaman aralığında tekrar ve ağırlık verisi bulunmuyor.',
            color: '#9ca3b4', font: { size: 13, weight: '500' }, padding: 20,
          },
          tooltip: {
            backgroundColor: 'rgba(20, 22, 32, 0.96)',
            borderColor: 'rgba(108, 99, 255, 0.55)',
            borderWidth: 1,
            titleColor: '#e8eaf0', bodyColor: '#d1d5e0', padding: 12,
            callbacks: {
              title: context => context[0]?.label || '',
              label: context => {
                const day = daySummaries[context.dataIndex];
                if (!day) return '';
                return context.dataset.yAxisID === 'yWeight'
                  ? `  En ağır set: ${day.maxWeight} kg`
                  : `  Bu ağırlıkta tekrar: ${day.repsAtMaxWeight}`;
              },
              afterBody: context => {
                const day = daySummaries[context[0]?.dataIndex];
                if (!day) return '';
                const allSets = day.sets
                  .sort((a, b) => a.set - b.set)
                  .map(set => `  Set ${set.set}: ${set.weightKg} kg × ${set.reps}`);
                return ['───────', '  Günün tüm setleri:', ...allSets];
              },
            },
          },
        },
        scales: {
          x: {
            grid: { display: false },
            ticks: { color: '#9ca3b4', maxRotation: 45, maxTicksLimit: 12 },
            title: { display: true, text: 'Tarih', color: '#9ca3b4' },
          },
          yWeight: {
            type: 'linear', position: 'left', beginAtZero: false,
            grid: { color: 'rgba(255, 255, 255, 0.05)' },
            ticks: { color: '#a9a6ff', callback: value => `${value} kg` },
            title: { display: true, text: 'Ağırlık (kg)', color: '#a9a6ff' },
          },
          yReps: {
            type: 'linear', position: 'right', beginAtZero: false,
            grid: { drawOnChartArea: false },
            ticks: { color: '#86efac', precision: 0 },
            title: { display: true, text: 'Tekrar', color: '#86efac' },
          },
        },
      },
    });
    _playHxBeamReveal(_exerciseProgressChart, '#22c55e');
    return;
  }
  let labels = [], chartPoints = [];
  if (points.length === 0) {
    labels = ['Veri Yok'];
  } else {
    const groups = new Map();
    for (const point of points) {
      const key = point.iso.toISOString().split('T')[0];
      if (!groups.has(key)) groups.set(key, { dateIso: key, tr: point.label, sets: [] });
      groups.get(key).sets.push(point);
    }
    for (const group of [...groups.values()].sort((a, b) => a.dateIso.localeCompare(b.dateIso))) {
      const maxSet = group.sets.reduce((current, item) => (item.value > current.value ? item : current), group.sets[0]);
      labels.push(group.tr);
      chartPoints.push({ y: maxSet.value, daySets: group.sets });
    }
  }

  const gradient = ctx.createLinearGradient(0, 0, 0, 400);
  gradient.addColorStop(0, 'rgba(108, 99, 255, 0.45)');
  gradient.addColorStop(1, 'rgba(108, 99, 255, 0.0)');
  _exerciseProgressChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        label: exName ? exName + ' — ' + metricLabel : metricLabel,
        data: chartPoints.length ? chartPoints.map(point => point.y) : [0],
        borderColor: '#6c63ff', borderWidth: 3, backgroundColor: gradient, fill: true, tension: 0.3,
        pointBackgroundColor: '#22c55e', pointBorderColor: '#ffffff', pointBorderWidth: 2, pointRadius: 6, pointHoverRadius: 9
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: _hxChartAnimation(),
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: 'rgba(20, 22, 32, 0.95)', borderColor: 'rgba(108, 99, 255, 0.5)', borderWidth: 1,
          titleColor: '#e8eaf0', bodyColor: '#d1d5e0', padding: 12,
          callbacks: {
            title: context => context[0].label,
            label: context => {
              const point = chartPoints[context.dataIndex];
              if (!point) return '';
              const sets = point.daySets || [{ value: context.parsed.y, reps: null, weightKg: 0 }];
              const lines = sets.map(set => metricType === 'reps'
                ? `  ${set.reps} tekrar`
                : `  ${set.weightKg} kg${set.reps ? ` × ${set.reps} tekrar` : ''}`);
              if (sets.length > 1) {
                const prMax = sets.reduce((maximum, set) => Math.max(maximum, set.value), 0);
                lines.push('───────', `  ${sets.length} set oynatıldı`, `  PR: ${prMax}${metricSuffix}`);
              }
              return lines;
            }
          }
        }
      },
      scales: {
        y: { beginAtZero: false, grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: '#9ca3b4', callback: value => `${value}${metricSuffix}` } },
        x: { grid: { display: false }, ticks: { color: '#9ca3b4', maxRotation: 45, maxTicksLimit: 12 } }
      }
    }
  });
  _playHxBeamReveal(_exerciseProgressChart, '#6c63ff');
}

/* ═══════════════════════════════════════════════
   NUTRITION (Beslenme)
═══════════════════════════════════════════════ */
let _macroChart = null;

/* ---------- Tarih Seçici Yardımcısı (Geriye Dönük Kayıt) ---------- */
// Tarihin TR görünümünü (14.08.2026) display input'una yaz
function _updateNutriDateDisplay() {
  const dateInput = document.getElementById('inputNutriDate');
  const display = document.getElementById('nutriDateDisplay');
  if (!dateInput || !display) return;
  const v = dateInput.value;
  if (!v) { display.value = ''; return; }
  const [y, m, d] = v.split('-');
  display.value = `${d}.${m}.${y}`;
}
function _initNutriDatePicker() {
  const dateInput = document.getElementById('inputNutriDate');
  if (!dateInput) return;
  const today = new Date().toISOString().split('T')[0];
  dateInput.max = today; // gelecek tarih seçilemez
  dateInput.addEventListener('change', _updateNutriDateDisplay);
  _updateNutriDateDisplay();
}
function _openNutriDatePicker() {
  const dateInput = document.getElementById('inputNutriDate');
  if (!dateInput) return;
  // Modern tarayıcıda native takvim açılır; desteklenmiyorsa doğrudan focus
  try { dateInput.showPicker(); } catch (e) { dateInput.focus(); }
}
let _nutritionStatsChart = null;
let _nutriCurrentPeriod = 'weekly';
let _nutriCurrentMetric = 'calories';
let _nutriHistoryData = null;
let _currentNutriNote = '';

/* ---------- Sayfa Yükleme ---------- */
async function loadNutrition(username) {
  try {
    // 1) Kullanıcı hedefleri (analyze'den)
    const stats = await apiPost(`/api/analyze`, { stagnation_detected: false });
    // 2) Bugünün verisi
    const todayRes = await apiGet(`/api/nutrition/today`);
    const todayLog = todayRes.log || { calories: 0, protein: 0, carbs: 0, fat: 0 };
    // 3) Eğer bugün veri yoksa, son girilen veriyi bul
    const lastLog = await apiGet(`/api/nutrition/history`);
    let lastEntry = null;
    if (lastLog.history && lastLog.history.length > 0) {
      const todayStr = new Date().toISOString().split('T')[0];
      lastEntry = lastLog.history.find(l => l.date === todayStr) || null;
    }
    // 4) İstatistik kartları ve başlık
    _renderNutritionHeader(stats);
    // 5) Input'ları doldur (bugün varsa bugün, yoksa boş)
    _fillTodayInputs(lastEntry || todayLog);
    // 6) Macro bar chart
    _renderMacroPie(lastEntry || todayLog);
    // 7) İstatistik grafiği (Haftalık + Kalori varsayılan)
    _nutriCurrentPeriod = 'weekly';
    _nutriCurrentMetric = 'calories';
    await _loadNutritionStats(username, 'weekly', 'calories');
  } catch (e) {
    console.error('Nutrition load error:', e);
    toast('Beslenme sayfası yüklenemedi: ' + e.message, 'error');
  }
}

/* ---------- Input'ları Doldur ---------- */
function _fillTodayInputs(todayLog) {
  _initNutriDatePicker();
  const protInput = document.getElementById('inputProtein');
  const carbInput = document.getElementById('inputCarbs');
  const fatInput = document.getElementById('inputFat');
  const calInput = document.getElementById('inputCalories');
  if (protInput) protInput.value = todayLog.protein || '';
  if (carbInput) carbInput.value = todayLog.carbs || '';
  if (fatInput) fatInput.value = todayLog.fat || '';
  const cal = (todayLog.protein || 0) * 4 + (todayLog.carbs || 0) * 4 + (todayLog.fat || 0) * 9;
  if (calInput) calInput.value = cal || '';
  const noteInput = document.getElementById('inputNutriNotes');
  if (noteInput) noteInput.value = todayLog.notes || '';
  _currentNutriNote = todayLog.notes || '';
  // Form tarihi bugüne ayarla ve görüntüsünü güncelle
  const dateInput = document.getElementById('inputNutriDate');
  if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];
  _updateNutriDateDisplay();
  _attachCalorieAutoCalc();
  // Hedefler tanımlıysa barları güncelle, yoksa sadece input'ları doldur
  if (window._nutriTargets) {
    _updateProgressBars({
      calories: cal,
      protein: todayLog.protein || 0,
      carbs: todayLog.carbs || 0,
      fat: todayLog.fat || 0,
      _targets: window._nutriTargets
    });
  }
}

/* ---------- Anlık Kalori Hesaplama ---------- */
function _attachCalorieAutoCalc() {
  const cal = parseFloat(document.getElementById('inputCalories')?.value) || 0;
  const prot = parseFloat(document.getElementById('inputProtein')?.value) || 0;
  const carb = parseFloat(document.getElementById('inputCarbs')?.value) || 0;
  const fat = parseFloat(document.getElementById('inputFat')?.value) || 0;
  const total = (prot * 4) + (carb * 4) + (fat * 9);
  const calInput = document.getElementById('inputCalories');
  if (calInput) calInput.value = total || '';
  const calTarget = (window._nutriTargets && window._nutriTargets.calories);
  const calPct = Math.min(100, (total / calTarget) * 100);
  const calBar = document.getElementById('calProgressBar');
  const calText = document.getElementById('calProgressText');
  if (calBar) calBar.style.width = `${calPct}%`;
  if (calText) calText.textContent = `${Math.round(total)}${total ? ' / ' + Math.round(calTarget) : ''} kcal`;
}

/* ---------- Progress Bar Güncelle ---------- */
function _updateProgressBars(data) {
  const t = data._targets || window._nutriTargets || {};
  const calTarget = t.calories || 2500;
  const calPct = calTarget > 0 ? Math.min(100, ((data.calories || 0) / calTarget) * 100) : 0;
  _setProgress('calProgressBar', 'calProgressText', calPct, data.calories || 0, calTarget, 'kcal', true);
  const protTarget = t.protein || 150;
  const protPct = protTarget > 0 ? Math.min(100, ((data.protein || 0) / protTarget) * 100) : 0;
  _setProgress('proteinProgressBar', 'proteinProgressText', protPct, data.protein || 0, protTarget, 'g', true);
  const carbTarget = t.carbs || 300;
  const carbPct = carbTarget > 0 ? Math.min(100, ((data.carbs || 0) / carbTarget) * 100) : 0;
  _setProgress('carbProgressBar', 'carbProgressText', carbPct, data.carbs || 0, carbTarget, 'g');
  const fatTarget = t.fat || 70;
  const fatPct = fatTarget > 0 ? Math.min(100, ((data.fat || 0) / fatTarget) * 100) : 0;
  _setProgress('fatProgressBar', 'fatProgressText', fatPct, data.fat || 0, fatTarget, 'g');
}

function _setProgress(barId, textId, pct, current, target, unit, isMacro) {
  const bar = document.getElementById(barId);
  const text = document.getElementById(textId);
  if (bar) bar.style.width = `${pct}%`;
  if (text) {
    if (isMacro) text.textContent = `${Math.round(current)}${unit} / ${Math.round(target)}${unit === 'kcal' ? ' kcal' : 'g'}`;
    else text.textContent = `${Math.round(current)} / ${Math.round(target)} ${unit}`;
  }
}

/* ---------- İstatistik Başlığı (Hedef Kartları) ---------- */
function _renderNutritionHeader(stats) {
  const header = document.getElementById('nutritionStatsHeader');
  if (!header) return;
  const macro = stats.macro || { protein: 160, carbs: 250, fat: 70 };
  const targetCal = stats.target_calories || 2400;
  window._nutriTargets = {
    calories: targetCal,
    protein: macro.protein,
    carbs: macro.carbs,
    fat: macro.fat
  };
  header.innerHTML = `
    <div class="stats-grid mb-20" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(130px, 1fr)); gap:10px; margin-bottom:20px; min-width:0;">
      <div style="padding:12px; border-radius:8px; background:rgba(108,99,255,0.12); border:2px solid var(--accent, #6c63ff);">
        <div style="font-size:11px; color:var(--text-muted);">HEDEF KALORİ</div>
        <div style="font-size:18px; font-weight:800; color:var(--accent, #6c63ff);">${Math.round(targetCal)} kcal</div>
      </div>
      <div style="padding:12px; border-radius:8px; background:rgba(34,197,94,0.12); border:1px solid rgba(34,197,94,0.3);">
        <div style="font-size:11px; color:var(--text-muted);">PROTEİN HEDEFİ</div>
        <div style="font-size:18px; font-weight:800; color:#22c55e;">${macro.protein} g</div>
      </div>
      <div style="padding:12px; border-radius:8px; background:rgba(245,158,11,0.12); border:1px solid rgba(245,158,11,0.3);">
        <div style="font-size:11px; color:var(--text-muted);">KARB HEDEFİ</div>
        <div style="font-size:18px; font-weight:800; color:#f59e0b;">${macro.carbs} g</div>
      </div>
      <div style="padding:12px; border-radius:8px; background:rgba(59,130,246,0.12); border:1px solid rgba(59,130,246,0.3);">
        <div style="font-size:11px; color:var(--text-muted);">YAĞ HEDEFİ</div>
        <div style="font-size:18px; font-weight:800; color:#3b82f6;">${macro.fat} g</div>
      </div>
    </div>`;
}

/* ---------- Makro Bar Chart (Yüzdelik) ---------- */
function _renderMacroPie(data) {
  const ctx = document.getElementById('macroChart');
  if (!ctx) return;
  if (_macroChart) _macroChart.destroy();
  const prot = data.protein || 0;
  const carb = data.carbs || 0;
  const fat = data.fat || 0;
  const total = prot + carb + fat;
  _macroChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: ['Toplam Makro Alımı'],
      datasets: [
        { label: 'Protein', data: total > 0 ? [(prot / total) * 100] : [0], backgroundColor: '#22c55e', borderRadius: total > 0 ? { topLeft: 4, bottomLeft: 4 } : 4 },
        { label: 'Karbonhidrat', data: total > 0 ? [(carb / total) * 100] : [0], backgroundColor: '#f59e0b' },
        { label: 'Yağ', data: total > 0 ? [(fat / total) * 100] : [0], backgroundColor: '#3b82f6', borderRadius: total > 0 ? { topRight: 4, bottomRight: 4 } : 4 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { position: 'right', labels: { color: '#9ca3b4', font: { size: 11 }, padding: 10, usePointStyle: true } },
        tooltip: {
          callbacks: {
            label: function(ctx) {
              const pct = ctx.parsed.x;
              let label = ctx.dataset.label;
              if (label === 'Protein') label += ` (${prot}g)`;
              else if (label === 'Karbonhidrat') label += ` (${carb}g)`;
              else if (label === 'Yağ') label += ` (${fat}g)`;
              return ` ${label}: %${pct.toFixed(1)}`;
            }
          }
        }
      },
      scales: {
        x: {
          stacked: true, max: 100,
          grid: { display: false },
          ticks: { callback: value => '%' + value, color: '#9ca3b4' }
        },
        y: { stacked: true, grid: { display: false }, ticks: { color: '#9ca3b4' } }
      }
    }
  });
}

/* ---------- Kaydet ---------- */
async function handleNutritionSubmit(e) {
  e.preventDefault();
  const btn = document.getElementById('btnSaveNutrition');
  const status = document.getElementById('nutriSaveStatus');
  if (btn) btn.disabled = true;
  try {
    const protein = parseFloat(document.getElementById('inputProtein').value) || 0;
    const carbs = parseFloat(document.getElementById('inputCarbs').value) || 0;
    const fat = parseFloat(document.getElementById('inputFat').value) || 0;
    const calories = (protein * 4) + (carbs * 4) + (fat * 9);
    const selectedLogDate = (document.getElementById('inputNutriDate')?.value || '').trim();
    const today = new Date().toISOString().split('T')[0];
    let logDate = today;
    if (selectedLogDate) {
      // Seçilen tarih bugünden ileri olamaz — güvenlik olarak yine bugüne düşür
      logDate = selectedLogDate > today ? today : selectedLogDate;
    }
    const notes = document.getElementById('inputNutriNotes')?.value || '';
    if (protein === 0 && carbs === 0 && fat === 0) {
      if (status) status.textContent = '⚠️ En az bir makro değeri gir';
      if (btn) btn.disabled = false;
      return;
    }
    const res = await apiPost('/api/nutrition/log', {
      username: _currentUser.username,
      log_date: logDate,
      protein, carbs, fat, calories, notes
    });
    if (res.success) {
      if (status) status.textContent = '✓ Kaydedildi';
      toast('Beslenme verisi kaydedildi', 'success');
      _currentNutriNote = notes;
      await loadNutrition(_currentUser.username);
    } else {
      if (status) status.textContent = '⚠️ Kayıt başarısız';
      toast('Kayıt başarısız: ' + (res.detail || 'Bilinmeyen hata'), 'error');
    }
  } catch (err) {
    console.error('Save error:', err);
    toast('Kayıt hatası: ' + err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function clearNutritionInputs() {
  const prot = document.getElementById('inputProtein');
  const carb = document.getElementById('inputCarbs');
  const fat = document.getElementById('inputFat');
  const cal = document.getElementById('inputCalories');
  if (prot) prot.value = '';
  if (carb) carb.value = '';
  if (fat) fat.value = '';
  if (cal) cal.value = '';
  const noteInput = document.getElementById('inputNutriNotes');
  if (noteInput) noteInput.value = '';
  _currentNutriNote = '';
  // Tarihi bugüne sıfırla ve görüntüyü güncelle
  const dateInput = document.getElementById('inputNutriDate');
  if (dateInput) dateInput.value = new Date().toISOString().split('T')[0];
  _updateNutriDateDisplay();
  if (window._nutriTargets) {
    _updateProgressBars({ calories: 0, protein: 0, carbs: 0, fat: 0, _targets: window._nutriTargets });
  }
  // Bugünkü makro kartını da sıfırla (yapıştırılmış kart yoksa güvenli)
  if (_macroChart) { _macroChart.destroy(); _macroChart = null; }
  const ctx = document.getElementById('macroChart');
  if (ctx) _macroChart = new Chart(ctx, { type: 'bar', data: { labels: ['Toplam Makro Alımı'], datasets: [] }, options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y' } });
}

/* ---------- İstatistik Kartı Seçimi (Kalori / Protein / Karb / Yağ) ---------- */
function selectNutriMetric(metric) {
  _nutriCurrentMetric = metric;
  // Kart aktiflik
  ['calories', 'protein', 'carbs', 'fat'].forEach(m => {
    const card = document.getElementById('nutriCard_' + m);
    if (!card) return;
    const isActive = m === metric;
    const colors = {
      calories: { bg: 'rgba(108,99,255,0.12)', border: '#6c63ff' },
      protein: { bg: 'rgba(34,197,94,0.12)', border: '#22c55e' },
      carbs: { bg: 'rgba(245,158,11,0.12)', border: '#f59e0b' },
      fat: { bg: 'rgba(59,130,246,0.12)', border: '#3b82f6' }
    };
    card.style.background = isActive ? colors[m].bg : 'rgba(255,255,255,0.02)';
    card.style.border = isActive ? `2px solid ${colors[m].border}` : '1px solid rgba(255,255,255,0.06)';
  });
  // Veri varsa grafik güncelle
  if (_nutriHistoryData) {
    _renderNutritionStatsChart(_nutriHistoryData.timeline, _nutriCurrentMetric);
  }
}

/* ---------- Zaman Dilimi Değişimi (Haftalık / Aylık / Genel) ---------- */
async function switchNutriStatsTimeframe(period) {
  _nutriCurrentPeriod = period;
  ['weekly', 'monthly', 'all'].forEach(p => {
    const pill = document.getElementById('nutriTime_' + p);
    if (pill) pill.classList.toggle('active', p === period);
  });
  await _loadNutritionStats(_currentUser.username, period, _nutriCurrentMetric);
}

/* ---------- İstatistik Verilerini Yükle ---------- */
async function _loadNutritionStats(username, period, metric) {
  try {
    const res = await apiGet(`/api/nutrition/history`);
    const history = res.history || [];
    // Filtreleme
    let filtered = history;
    if (period === 'weekly') {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - 7);
      const cutoffStr = cutoff.toISOString().split('T')[0];
      filtered = history.filter(h => h.date >= cutoffStr);
    } else if (period === 'monthly') {
      const cutoff = new Date();
      cutoff.setMonth(cutoff.getMonth() - 1);
      const cutoffStr = cutoff.toISOString().split('T')[0];
      filtered = history.filter(h => h.date >= cutoffStr);
    }
    // Tarihe göre sırala (en eski -> en yeni)
    filtered.sort((a, b) => a.date.localeCompare(b.date));
    // Veriyi sakla
    _nutriHistoryData = { timeline: filtered, period: period };
    // Ortalama değerleri hesapla
    if (filtered.length > 0) {
      const avgCal = filtered.reduce((s, d) => s + (d.calories || 0), 0) / filtered.length;
      const avgProt = filtered.reduce((s, d) => s + (d.protein || 0), 0) / filtered.length;
      const avgCarb = filtered.reduce((s, d) => s + (d.carbs || 0), 0) / filtered.length;
      const avgFat = filtered.reduce((s, d) => s + (d.fat || 0), 0) / filtered.length;
      _setText('avgCaloriesText', `${Math.round(avgCal)} kcal`);
      _setText('avgProteinText', `${Math.round(avgProt)}g`);
      _setText('avgCarbsText', `${Math.round(avgCarb)}g`);
      _setText('avgFatText', `${Math.round(avgFat)}g`);
    } else {
      _setText('avgCaloriesText', '0 kcal');
      _setText('avgProteinText', '0g');
      _setText('avgCarbsText', '0g');
      _setText('avgFatText', '0g');
    }
    // Grafiği çiz
    _renderNutritionStatsChart(filtered, metric);
  } catch (e) {
    console.error('Stats load error:', e);
    toast('İstatistik yüklenemedi: ' + e.message, 'error');
  }
}

/* ---------- İstatistik Grafiği ---------- */
function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _renderNutritionStatsChart(timeline, metric) {
  const ctx = document.getElementById('nutritionStatsChart');
  if (!ctx) return;
  _registerHxBeamPlugin();
  if (_nutritionStatsChart) _nutritionStatsChart.destroy();
  const isLight = document.body.classList.contains('light-mode');
  const gridColor = isLight ? 'rgba(0,0,0,0.08)' : 'rgba(255,255,255,0.06)';
  const textColor = isLight ? '#6b7280' : '#9ca3b4';
  if (timeline.length === 0) {
    _nutritionStatsChart = new Chart(ctx, {
      type: 'line',
      data: { labels: ['Veri yok'], datasets: [{ data: [0], borderColor: 'rgba(255,255,255,0.1)', borderWidth: 1 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } }
    });
    _playHxBeamReveal(_nutritionStatsChart, '#6c63ff');
    return;
  }
  const config = {
    calories: { label: 'Kalori (kcal)', color: '#6c63ff', bg: 'rgba(108,99,255,0.15)', key: 'calories', unit: 'kcal' },
    protein: { label: 'Protein (g)', color: '#22c55e', bg: 'rgba(34,197,94,0.15)', key: 'protein', unit: 'g' },
    carbs: { label: 'Karbonhidrat (g)', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)', key: 'carbs', unit: 'g' },
    fat: { label: 'Yağ (g)', color: '#3b82f6', bg: 'rgba(59,130,246,0.15)', key: 'fat', unit: 'g' }
  };
  const c = config[metric];
  const values = timeline.map(d => d[c.key] || 0);
  _nutritionStatsChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: timeline.map(d => {
        const dt = new Date(d.date);
        return dt.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' });
      }),
      datasets: [{
        label: c.label,
        data: values,
        borderColor: c.color,
        backgroundColor: c.bg,
        fill: true,
        tension: 0.4,
        pointRadius: 5,
        pointBackgroundColor: c.color,
        pointBorderColor: c.color,
        pointHoverRadius: 7,
        borderWidth: 2.5
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: _hxChartAnimation(),
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: isLight ? '#fff' : '#1e2231',
          titleColor: isLight ? '#1a1d27' : '#e8eaf0',
          bodyColor: isLight ? '#6b7280' : '#9ca3b4',
          borderColor: isLight ? '#e2e5ec' : '#2a2f3e',
          borderWidth: 1,
          cornerRadius: 8,
          padding: 10,
          callbacks: { label: function(ctx) { return ` ${ctx.parsed.y} ${c.unit}`; } }
        }
      },
      scales: {
        x: { grid: { color: gridColor }, ticks: { color: textColor, font: { size: 11 }, maxRotation: 45 } },
        y: {
          grid: { color: gridColor },
          ticks: { color: textColor, font: { size: 11 } },
          title: { display: true, text: c.unit, color: textColor },
          beginAtZero: true
        }
      }
    }
  });
  _playHxBeamReveal(_nutritionStatsChart, c.color);
}

// ═══════════════════════════════════════════════
// ÖZEL PROGRAM OLUŞTURUCU
// ═══════════════════════════════════════════════

let currentActiveWeekIndex = 0;

// Sadece 1 haftalık varsayılan şablon (Kullanıcı dilerse büyütecek)
let customProgramData = [
  [
    { day: "Pazartesi", type: "Push (Göğüs & Omuz)", focus: "Genel Hacim", isRest: false },
    { day: "Salı", type: "Pull (Sırt & Biceps)", focus: "Genişlik", isRest: false },
    { day: "Çarşamba", type: "Legs (Bacak)", focus: "Squat", isRest: false },
    { day: "Perşembe", type: "Rest Day (Dinlenme)", focus: "Toparlanma", isRest: true },
    { day: "Cuma", type: "Upper (Üst Vücut)", focus: "Kuvvet", isRest: false },
    { day: "Cumartesi", type: "Lower (Alt Vücut)", focus: "Hipertrofi", isRest: false },
    { day: "Pazar", type: "Rest Day (Dinlenme)", focus: "Toparlanma", isRest: true }
  ]
];

// 1. Sayfa ilk açıldığında çalışacak fonksiyon
async function loadCustomProgram() {
  // Dashboard daha önce yüklenmediyse de merkezi kullanıcı kaydını al.
  if (!cachedUserData) {
    try {
      cachedUserData = await apiGet('/api/dashboard');
      lastConfirmedCustomSplitJson = normalizeCustomSplitJson(cachedUserData.user?.custom_split);
    } catch (error) {
      toast(error.message || 'Özel program yüklenemedi.', 'error');
    }
  }

  try {
    const savedProgram = JSON.parse(cachedUserData?.user?.custom_split || '[]');
    if (Array.isArray(savedProgram) && savedProgram.length > 0) {
      customProgramData = savedProgram;
    }
  } catch (_) {
    // Bozuk/eski bir kayıt varsayılan şablonu bozmasın.
  }

  currentActiveWeekIndex = Math.min(currentActiveWeekIndex, customProgramData.length - 1);
  renderWeekTabs();
  switchProgramWeek(currentActiveWeekIndex);
}

// 2. Sekmeleri ve Sağ Üst Çarpı (X) Butonlarını Çizen Fonksiyon
function renderWeekTabs() {
  const container = document.getElementById('weekTabsContainer');
  if (!container) return;

  let tabsHTML = '';

  // Var olan haftaları çiz
  customProgramData.forEach((week, index) => {
    const isActive = index === currentActiveWeekIndex;
    const bg = isActive ? 'var(--accent-soft)' : 'var(--bg-primary)';
    const border = isActive ? 'var(--accent)' : 'var(--border)';
    const color = isActive ? 'var(--accent)' : 'var(--text-muted)';

    // KURAL: 1. Hafta (index === 0) asla silinemez. Sadece sonradan eklenen haftalara (index > 0) çarpı koyulur.
    const isDeletable = index > 0;

    tabsHTML += `
      <div style="position:relative; display:inline-block; margin-top:6px; margin-right:12px;">
        <button onclick="switchProgramWeek(${index})"
                style="padding:10px 22px; border-radius:8px; border:1px solid ${border}; background:${bg}; color:${color}; font-weight:700; cursor:pointer; white-space:nowrap; transition:all 0.2s;">
          ${index + 1}. Hafta
        </button>

        ${isDeletable ? `
          <span onclick="deleteWeek(${index}, event)"
                title="Bu Haftayı Sil"
                style="position:absolute; top:-8px; right:-8px; background:#ef4444; color:#ffffff; width:15px; height:15px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:bold; cursor:pointer; box-shadow:0 2px 6px rgba(0,0,0,0.3); z-index:10; transition:transform 0.2s;"
                onmouseover="this.style.transform='scale(1.2)'"
                onmouseout="this.style.transform='scale(1)'">
            ✕
          </span>
        ` : ''}
      </div>
    `;
  });

  // + Yeni Hafta Ekleme Butonu
  tabsHTML += `
    <div style="display:inline-block; margin-top:6px;">
      <button onclick="addNewWeek()" title="Yeni Hafta Ekle"
              style="padding:10px 16px; border-radius:8px; border:1px dashed var(--accent); background:transparent; color:var(--accent); font-weight:700; cursor:pointer; display:flex; align-items:center; gap:6px; transition:all 0.2s;">
        <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M12 4v16m8-8H4"></path></svg>
        Ekle
      </button>
    </div>
  `;

  container.innerHTML = tabsHTML;
}

// 3. Haftalar Arası Geçiş
function switchProgramWeek(index) {
  currentActiveWeekIndex = index;
  renderWeekTabs(); // Sekme renklerini güncelle

  const titleEl = document.getElementById('currentWeekTitle');
  if (titleEl) titleEl.textContent = `${index + 1}. Hafta Günlük Dağılımı`;

  renderCustomWeekDays(index);
}

// 4. Yeni Hafta Ekleme
function addNewWeek() {
  const newWeekTemplate = [
    { day: "Pazartesi", type: "", focus: "", isRest: false },
    { day: "Salı", type: "", focus: "", isRest: false },
    { day: "Çarşamba", type: "", focus: "", isRest: false },
    { day: "Perşembe", type: "", focus: "", isRest: false },
    { day: "Cuma", type: "", focus: "", isRest: false },
    { day: "Cumartesi", type: "", focus: "", isRest: false },
    { day: "Pazar", type: "", focus: "", isRest: false }
  ];

  customProgramData.push(newWeekTemplate);
  const newIndex = customProgramData.length - 1;

  // Yeni haftaya otomatik geç
  switchProgramWeek(newIndex);
}

// 5. Hafta Silme
function deleteWeek(index, event) {
  if (event) event.stopPropagation(); // Butona tıklamanın sekmeye geçmesini engeller

  if (index === 0) return; // Güvenlik: 1. Hafta silinemez

  if (confirm(`${index + 1}. Haftayı silmek istediğinden emin misin?`)) {
    customProgramData.splice(index, 1);

    // Eğer silinen hafta şu an aktif haftaysa bir öncekine kay
    if (currentActiveWeekIndex >= customProgramData.length) {
      currentActiveWeekIndex = customProgramData.length - 1;
    }

    switchProgramWeek(currentActiveWeekIndex);
  }
}

// 6. Seçili Haftanın Gün Kartlarını Çizme
function renderCustomWeekDays(weekIndex) {
  const daysList = customProgramData[weekIndex];
  const container = document.getElementById('customDaysContainer');
  if (!container) return;

  let html = '';

  daysList.forEach((d, dayIndex) => {
    // Dinlenme günüyse inputları kilitle ve soluklaştır
    const isDisabled = d.isRest ? 'disabled' : '';
    const opacityStyle = d.isRest ? '0.4' : '1';
    const bgStyle = d.isRest ? 'background:rgba(255,255,255,0.01);' : 'background:rgba(255,255,255,0.03);';

    html += `
      <div class="custom-day-card-animated" style="--card-index: ${dayIndex}; display:flex; align-items:center; gap:16px; ${bgStyle} border:1px solid rgba(255,255,255,0.08); padding:14px 18px; border-radius:10px; transition:0.5s;">

        <div style="min-width:90px; font-weight:700; color:var(--accent); font-size:14px; opacity:${opacityStyle}; transition:0.5s;">
          ${d.day}
        </div>

        <div style="flex:2;">
          <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:4px;">Antrenman / Split Tipi</label>
          <input type="text" value="${d.isRest && !d.type ? 'Dinlenme' : d.type}" onchange="updateDayData(${weekIndex}, ${dayIndex}, 'type', this.value)"
                 placeholder="Örn: Push, Pull, Bacak..." ${isDisabled}
                 style="width:100%; background:var(--bg-primary); border:1px solid var(--border); color:var(--text); padding:8px 12px; border-radius:6px; font-size:13px; outline:none; opacity:${opacityStyle}; transition:0.5s;">
        </div>

        <div style="flex:1.5;">
          <label style="font-size:11px; color:var(--text-muted); display:block; margin-bottom:4px;">Odak Noktası</label>
          <input type="text" value="${d.isRest && !d.focus ? 'Toparlanma' : d.focus}" onchange="updateDayData(${weekIndex}, ${dayIndex}, 'focus', this.value)"
                 placeholder="Örn: Üst Göğüs" ${isDisabled}
                 style="width:100%; background:var(--bg-primary); border:1px solid var(--border); color:var(--text); padding:8px 12px; border-radius:6px; font-size:13px; outline:none; opacity:${opacityStyle}; transition:0.5s;">
        </div>

        <div style="display:flex; flex-direction:column; align-items:center; min-width:80px;">
          <label style="font-size:11px; color:var(--text-muted); margin-bottom:6px;">Dinlenme?</label>
          <input type="checkbox" ${d.isRest ? 'checked' : ''} onchange="updateDayData(${weekIndex}, ${dayIndex}, 'isRest', this.checked)"
                 style="width:18px; height:18px; cursor:pointer; accent-color:var(--accent);">
        </div>
      </div>
    `;
  });

  container.innerHTML = html;
}

// 7. Input Değişikliklerini Veriye Kaydetme
function updateDayData(weekIndex, dayIndex, field, value) {
  customProgramData[weekIndex][dayIndex][field] = value;

  // Eğer checkbox'a (isRest) tıklandıysa, disable efekti için o haftayı anında yeniden çiz!
  if (field === 'isRest') {
    renderCustomWeekDays(weekIndex);
  }
}

// 8. Kaydet Butonu
async function saveCustomProgram() {
  // Sistemde giriş yapmış olan kullanıcının adını al (Dashboard'da kullandığın değişkenden çekebilirsin)
  // Örnek olarak localStorage'dan veya mevcut fonksiyondan username'i bulmalısın.
  // Şimdilik test için statik yazıyorum, kendi sistemindeki currentUser değişkenine eşitle:
  const username = window._currentUsername ||
                   (typeof _currentUser !== 'undefined' ? _currentUser?.username : null) ||
                   localStorage.getItem('username');

  // Oturum kontrolü: Eğer kullanıcı adı bulunamazsa işlemi durdur ve uyar
  if (!username) {
    alert("❌ Oturum açmış kullanıcı bulunamadı! Lütfen giriş yapıp tekrar deneyin.");
    return;
  }

  const requestBody = {
    username: username,
    program: customProgramData
  };

  try {
    const result = await apiPost('/api/custom-program', requestBody);
    const savedProgram = Array.isArray(result.program) ? result.program : customProgramData;
    const savedProgramJson = JSON.stringify(savedProgram);

    if (cachedUserData?.user) {
      cachedUserData.user.custom_split = savedProgramJson;
    }
    lastConfirmedCustomSplitJson = savedProgramJson;
    toast(result.message || 'Özel program hesabınıza kaydedildi.', 'success');
  } catch (err) {
    console.error('Sunucuya gönderilirken hata oluştu:', err);
    toast(err.message || 'Özel program kaydedilemedi.', 'error');
  }
}


/* ═══════════════════════════════════════════════
   PROFILE
═══════════════════════════════════════════ */
async function loadProfile(username) {
  const user = await apiGet(`/api/user`);
  document.getElementById('profAge').value = user.age || '';
  document.getElementById('profGender').value = user.gender || 'male';
  document.getElementById('profHeight').value = user.height || '';
  document.getElementById('profWeight').value = user.weight || '';
  document.getElementById('profLevel').value = user.fitness_level || 'Beginner';
  document.getElementById('profGoal').value = user.goal || 'bulk';
  document.getElementById('profDays').value = user.days_per_week || '4';
  document.getElementById('profSession').value = user.session_time_mins || '60';
}

async function saveProfile() {
  const data = {
    username: _currentUser.username,
    age: parseInt(document.getElementById('profAge').value) || 0,
    gender: document.getElementById('profGender').value,
    height: parseFloat(document.getElementById('profHeight').value) || 170,
    weight: parseFloat(document.getElementById('profWeight').value) || 70,
    fitness_level: document.getElementById('profLevel').value,
    goal: document.getElementById('profGoal').value,
    days_per_week: parseInt(document.getElementById('profDays').value) || 4,
    session_time_mins: parseInt(document.getElementById('profSession').value) || 60
  };
  try {
    await apiPost('/api/user', data);
    toast('Profil kaydedildi!', 'success');
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

async function changePassword() {
  const oldP = document.getElementById('oldPassword').value;
  const newP = document.getElementById('newPassword').value;
  const confirmP = document.getElementById('newPasswordConfirm').value;

  if (!oldP || !newP) { toast('Tüm alanları doldurun', 'error'); return; }
  if (newP !== confirmP) { toast('Şifreler eşleşmiyor', 'error'); return; }
  if (newP.length < 3) { toast('Şifre en az 3 karakter olmalı', 'error'); return; }

  try {
    await apiPost('/api/auth/change-password', {
      username: _currentUser.username,
      old_password: oldP,
      new_password: newP
    });
    toast('Şifre güncellendi!', 'success');
    document.getElementById('oldPassword').value = '';
    document.getElementById('newPassword').value = '';
    document.getElementById('newPasswordConfirm').value = '';
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

/* ═══════════════════════════════════════════════
   ADMIN PANEL
═══════════════════════════════════════════════ */
async function loadAdminPanel() {
  const users = await apiGet('/api/admin/users');

  // Stats
  document.getElementById('adminTotalUsers').textContent = users.length;
  let totalW = 0, totalV = 0, totalBMI = 0, bmiCount = 0;

  // Load each user's workout count and volume
  for (const u of users) {
    try {
      const w = await apiGet(`/api/admin/workouts/${u.id}`);
      totalW += w.length;
      totalV += w.reduce((sum, wk) => sum + wk.total_volume, 0);
    } catch(e) {}
    if (u.height > 0 && u.weight > 0) {
      totalBMI += u.weight / ((u.height/100) ** 2);
      bmiCount++;
    }
  }

  document.getElementById('adminTotalWorkouts').textContent = totalW;
  document.getElementById('adminTotalVolume').textContent = Math.round(totalV).toLocaleString();
  document.getElementById('adminAvgBMI').textContent = bmiCount ? (totalBMI / bmiCount).toFixed(1) : '-';

  // Users table
  document.getElementById('adminUsersTable').innerHTML = users.map(u => {
    const bmi = (u.height > 0 && u.weight > 0) ? (u.weight / ((u.height/100)**2)).toFixed(1) : '-';
    return `<tr>
      <td>${u.id}</td>
      <td><strong>${u.username}</strong></td>
      <td>${u.age || '-'}</td>
      <td>${u.height || '-'}cm</td>
      <td>${u.weight || '-'}kg</td>
      <td><span class="badge badge-accent">${u.fitness_level}</span></td>
      <td><span class="badge badge-green">${u.goal}</span></td>
      <td>${bmi}</td>
      <td>${u.created_at?.split('T')[0] || '-'}</td>
      <td>
        <button class="btn btn-sm btn-secondary" onclick="adminLoadUser(${u.id},${JSON.stringify(u.age)},${u.weight},${u.height},'${u.fitness_level}','${u.goal}',${u.days_per_week},${u.session_time_mins})">Düzenle</button>
      </td>
    </tr>`;
  }).join('');
}

function adminLoadUser(id, age, weight, height, level, goal, days, session) {
  document.getElementById('editUserId').value = id;
  document.getElementById('editAge').value = age || '';
  document.getElementById('editWeight').value = weight || '';
  document.getElementById('editHeight').value = height || '';
  document.getElementById('editLevel').value = level;
  document.getElementById('editGoal').value = goal;
  document.getElementById('editDays').value = days || '';
  document.getElementById('editSession').value = session || '';
  document.getElementById('editNewPassword').value = '';
}

async function adminSaveUser() {
  const data = {
    user_id: parseInt(document.getElementById('editUserId').value),
    age: parseInt(document.getElementById('editAge').value) || undefined,
    weight: parseFloat(document.getElementById('editWeight').value) || undefined,
    height: parseFloat(document.getElementById('editHeight').value) || undefined,
    fitness_level: document.getElementById('editLevel').value,
    goal: document.getElementById('editGoal').value,
    days_per_week: parseInt(document.getElementById('editDays').value) || undefined,
    session_time_mins: parseInt(document.getElementById('editSession').value) || undefined,
  };
  const newPass = document.getElementById('editNewPassword').value;
  if (newPass) data.new_password = newPass;

  try {
    await apiPut('/api/admin/user', data);
    toast('Kullanıcı güncellendi!', 'success');
    loadAdminPanel();
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

async function adminDeleteUser() {
  const id = document.getElementById('editUserId').value;
  if (!id) { toast('Önce kullanıcı seçin', 'error'); return; }
  if (!confirm(`Kullanıcı ID ${id} ve tüm antrenmanlarını silmek istediğinize emin misiniz?`)) return;
  try {
    await apiDelete(`/api/admin/user/${id}`);
    toast('Kullanıcı silindi', 'success');
    document.getElementById('editUserId').value = '';
    loadAdminPanel();
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

async function adminViewUserWorkouts() {
  const userId = document.getElementById('adminViewUserId').value;
  if (!userId) { toast('Kullanıcı ID girin', 'error'); return; }
  try {
    const data = await apiGet(`/api/admin/workouts/${userId}`);
    const tbody = document.getElementById('adminWorkoutsTable');
    tbody.innerHTML = data.workouts.length ? data.workouts.map(w => `
      <tr>
        <td>${w.id}</td>
        <td>${w.date}</td>
        <td><span class="badge badge-accent">${w.session_type}</span></td>
        <td>${Math.round(w.total_volume).toLocaleString()} kg</td>
        <td>${w.exercises?.length || 0} hareket</td>
        <td><button class="btn btn-sm btn-danger" onclick="adminDeleteWorkout(${w.id})">Sil</button></td>
      </tr>
    `).join('') : '<tr><td colspan="6" style="text-align:center;color:var(--text-muted)">Antrenman kaydı yok</td></tr>';
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

async function adminDeleteWorkout(id) {
  if (!confirm('Bu antrenmanı silmek istediğinize emin misiniz?')) return;
  try {
    await apiDelete(`/api/admin/workout/${id}`);
    toast('Antrenman silindi', 'success');
    adminViewUserWorkouts();
  } catch(e) {
    toast('Hata: ' + e.message, 'error');
  }
}

function refreshAdminUsers() { loadAdminPanel(); }

/* ═══════════════════════════════════════════════
   INIT
═══════════════════════════════════════════════ */
(async function init() {
  loadTheme();
  const token = localStorage.getItem('hx_token');
  const uname = localStorage.getItem('hx_user');
  const savedIsAdmin = localStorage.getItem('hx_isAdmin');
  // Kayıtlı oturum yoksa → giriş ekranı
  if (!token || !uname) {
    showLogin();
    return;
  }
  // Kayıtlı şifre ile token'ı yenile (her oturum açışta geçerli JWT üret)
  const hxPass = localStorage.getItem('hx_pass');
  if (hxPass && uname !== 'admin') {
    try {
      const lr = await fetch(`${API}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: uname, password: hxPass })
      });
      if (lr.ok) {
        const ld = await lr.json();
        localStorage.setItem('hx_token', ld.token);
        _isAdmin = !!ld.is_admin;
        _currentUser = { ...ld };
        delete _currentUser.token;
      } else {
        throw new Error('token yenileme başarısız');
      }
    } catch(e) {
      // Yenileme başarısız → token'ı sil, giriş ekranı
      localStorage.removeItem('hx_token');
      localStorage.removeItem('hx_user');
      localStorage.removeItem('hx_loggedIn');
      localStorage.removeItem('hx_isAdmin');
      localStorage.removeItem('hx_pass');
      showLogin();
      return;
    }
  } else if (uname === 'admin') {
    // Admin: token zaten localStorage'da, kullanıcı bilgisi minimal
    _isAdmin = true;
    _currentUser = { username: uname, is_admin: true };
  } else {
    // Eski sürümden gelen oturum (hx_pass yok) — mevcut token ile /api/user dene
    try {
      const u = await apiGet('/api/user');
      _isAdmin = savedIsAdmin === '1';
      _currentUser = { ...u };
      // Şifreyi sakla ki bir sonraki açılışta token yenilensin
      localStorage.setItem('hx_pass', '___token_valid___');
    } catch(e) {
      showLogin();
      return;
    }
  }
  localStorage.setItem('hx_loggedIn', 'true');
  enterApp();
})();

// Yıl-Ay-Gün (YYYY-MM-DD) formatını Gün-Ay-Yıl (DD.MM.YYYY) formatına çeviren fonksiyon
function formatDateTR(dateString) {
  if (!dateString) return '';
  // Eğer tarih "2026-06-08" veya "2026-06-08 12:00:00" gibiyse parçala
  const parts = dateString.split(' ')[0].split('-');
  if (parts.length === 3) {
    return `${parts[2]}.${parts[1]}.${parts[0]}`; // Gün . Ay . Yıl
  }
  return dateString; // Zaten düzgünse olduğu gibi bırak
}

/* Enter key support */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    const loginPage = document.getElementById('loginPage');
    const regPage = document.getElementById('registerPage');
    if (!loginPage.classList.contains('hidden')) doLogin();
    else if (!regPage.classList.contains('hidden')) doRegister();
  }
});


/* ═══════════════════════════════════════════════
   UZMAN SİSTEMİ — VERİ TOPLAMA MERKEZİ
   Bu ekran analiz veya program önerisi üretmez. Kullanıcının bildirdiği
   hedef, kas ağrısı ve geçici kısıt verilerini tek uzman profiline kaydeder.
═══════════════════════════════════════════════ */
let expertDataState = null;
// Üstteki ana sekme sade tutulur; kas ağrısı ve sakatlık panelleri sağlık
// ebeveyni altında iki alt görünüm olarak çalışır.
let expertDataTab = 'health';
let expertDataHealthTab = 'doms';
let expertDataSetupTab = 'goals';
let expertDataPlanningTab = 'split';
let expertDataGoalDraft = { primary_goal: '', priority_muscles: [], priority_note: '' };
let expertDataGymDraft = null;
let expertDataInjuryDraft = null;
let expertDataDomsEditDraft = null;
let expertAnalysisState = null;
// HX_EXPERT_ANALYSIS_FLOW_FIX_V2
// HX_EXPERT_ANALYSIS_RESPONSE_UNWRAP_V1
// HX_RPE_RECOMMENDATION_PROGRAM_V1
let expertAnalysisLoadPromise = null;

function expertDataAnalysisFallback(error) {
  const message = String(error?.message || 'Bilinmeyen istek hatası');
  return {
    status: { title: 'Analiz geçici olarak yüklenemedi', tone: 'warning' },
    findings: [{
      title: 'Analiz isteği tamamlanamadı',
      category: 'Sistem',
      tone: 'warning',
      message: 'Verilerin korunuyor. Lütfen sayfayı yenileyip yeniden dene.',
      action: message,
    }],
    split_plan: {
      title: 'Split değerlendirmesi bekleniyor',
      summary: 'Analiz yanıtı alınamadığı için güvenli otomatik yönlendirme üretilemedi.',
      approach: 'Mevcut programın değiştirilmedi. Sayfayı yeniledikten sonra Analiz sekmesinden tekrar dene.',
      focus: [],
      monitor: [],
    },
  };
}

async function expertDataLoadAnalysis(force = false) {
  if (!force && expertAnalysisState) return expertAnalysisState;
  if (expertAnalysisLoadPromise) return expertAnalysisLoadPromise;

  expertAnalysisLoadPromise = (async () => {
    try {
      const response = await apiGet('/api/expert-data/analysis');
      if (!response || response.success !== true || !response.analysis || typeof response.analysis !== 'object') {
        throw new Error('Uzman analiz yanıtı beklenen biçimde gelmedi.');
      }
      // Endpoint { success, analysis } döndürür; arayüz yalnız içteki analiz nesnesini render eder.
      expertAnalysisState = response.analysis;
      return expertAnalysisState;
    } catch (error) {
      expertAnalysisState = expertDataAnalysisFallback(error);
      return expertAnalysisState;
    } finally {
      expertAnalysisLoadPromise = null;
      renderExpertSystem();
    }
  })();

  return expertAnalysisLoadPromise;
}

function expertDataInvalidateAnalysis() {
  expertAnalysisState = null;
}


let expertRpeDraft = { score: null };

function expertDataEscape(value) { return typeof expertEscape === 'function' ? expertEscape(value) : String(value ?? ''); }
function expertDataCatalog() { return expertDataState?.catalog || {}; }
function expertDataMuscles() { return Array.isArray(expertDataCatalog().detailed_muscles) ? expertDataCatalog().detailed_muscles : []; }
function expertDataMuscleLabel(id) {
  return expertDataMuscles().find(item => item.id === id)?.label || id || '—';
}
function expertDataGoalLabel(id) {
  return expertDataCatalog().primary_goals?.[id] || id || 'Belirtilmedi';
}
function expertDataProfileGoal() {
  const value = String(_currentUser?.goal || '').trim().toLowerCase();
  const aliases = { bulk: 'hypertrophy', hypertrophy: 'hypertrophy', muscle_gain: 'hypertrophy', strength: 'strength', cut: 'fat_loss', fat_loss: 'fat_loss', maintain: 'fat_loss', maintenance: 'fat_loss' };
  return aliases[value] || 'hypertrophy';
}
function expertDataToday() { return new Date().toISOString().slice(0, 10); }
function expertDataDate(value) {
  if (!value) return '—';
  const parts = String(value).slice(0, 10).split('-');
  return parts.length === 3 ? `${parts[2]}.${parts[1]}.${parts[0]}` : value;
}
function expertDataTone(value, type) {
  const number = Number(value || 0);
  if (type === 'pain') return number >= 4 ? '#ef476f' : number >= 2 ? '#ffb703' : '#26d0ce';
  return number >= 80 ? '#33d69f' : number >= 50 ? '#4dabf7' : '#ffb703';
}
function expertDataInjectStyles() {
  if (document.getElementById('expertDataCollectStyles')) return;
  const style = document.createElement('style');
  style.id = 'expertDataCollectStyles';
  style.textContent = `
    .expert-data-shell{max-width:1240px;margin:0 auto;display:grid;gap:18px}
    .expert-data-hero{position:relative;overflow:hidden;padding:24px;border:1px solid var(--border);border-radius:18px;background:linear-gradient(120deg,rgba(72,149,239,.17),rgba(38,208,206,.07) 55%,rgba(112,72,232,.13));box-shadow:0 14px 34px rgba(0,0,0,.12)}
    .expert-data-hero:after{content:'';position:absolute;width:260px;height:260px;right:-110px;top:-155px;border-radius:50%;background:radial-gradient(circle,rgba(38,208,206,.22),transparent 68%);pointer-events:none}
    .expert-data-eyebrow{display:inline-flex;align-items:center;gap:7px;padding:5px 9px;border:1px solid rgba(77,171,247,.35);border-radius:999px;color:#7cc4ff;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
    .expert-data-hero h2{position:relative;margin:11px 0 7px;font-size:clamp(21px,3vw,30px);color:var(--text-primary)}
    .expert-data-hero p{position:relative;max-width:760px;margin:0;color:var(--text-secondary);font-size:13px;line-height:1.65}
    .expert-data-tabs{display:flex;gap:8px;overflow-x:auto;padding:5px 1px 8px;scrollbar-width:thin}
    .expert-data-tab{flex:0 0 auto;display:flex;align-items:center;gap:8px;border:1px solid var(--border);background:var(--card-bg);color:var(--text-secondary);padding:10px 13px;border-radius:11px;font-size:12px;font-weight:750;cursor:pointer;transition:transform .2s ease,border-color .2s ease,background .2s ease,color .2s ease,box-shadow .2s ease}
    .expert-data-subtabs{display:flex;gap:8px;align-items:center;padding:0 0 15px;margin-bottom:18px;border-bottom:1px solid var(--border)}
    .expert-data-subtab{border:1px solid var(--border);background:rgba(77,171,247,.04);color:var(--text-secondary);padding:9px 12px;border-radius:10px;font-size:12px;font-weight:750;cursor:pointer;transition:background .18s ease,color .18s ease,border-color .18s ease,transform .18s ease}.expert-data-subtab:hover{transform:translateY(-1px);border-color:rgba(77,171,247,.7);color:var(--text-primary)}.expert-data-subtab.active{background:rgba(77,171,247,.16);border-color:#3aa5e6;color:#8bd4ff;box-shadow:0 5px 13px rgba(41,103,201,.14)}
    .expert-data-tab:hover{transform:translateY(-2px);border-color:#4dabf7;color:var(--text-primary)}
    .expert-data-tab.active{color:white;border-color:#378add;background:linear-gradient(135deg,#2967c9,#30a2d8);box-shadow:0 8px 18px rgba(41,103,201,.25)}
    .expert-data-stage{min-height:500px;animation:expertDataSlide .34s cubic-bezier(.2,.8,.2,1) both}
    @keyframes expertDataSlide{from{opacity:0;transform:translateY(13px) scale(.992)}to{opacity:1;transform:translateY(0) scale(1)}}
    .expert-data-grid{display:grid;grid-template-columns:minmax(0,1.45fr) minmax(290px,.75fr);gap:18px;align-items:start}
    .expert-data-card{border:1px solid var(--border);border-radius:16px;background:var(--card-bg);padding:19px;box-shadow:0 9px 23px rgba(0,0,0,.07)}
    .expert-data-card h3{margin:0;color:var(--text-primary);font-size:16px}.expert-data-card p{color:var(--text-muted);font-size:12px;line-height:1.58}
    .expert-data-cardhead{display:flex;align-items:start;justify-content:space-between;gap:12px;margin-bottom:13px}
    .expert-data-badge{flex:0 0 auto;padding:5px 8px;border-radius:999px;background:rgba(77,171,247,.12);color:#5fb7ff;font-size:10px;font-weight:800}
    .expert-data-metric-head,.expert-data-metric-row{display:grid;grid-template-columns:minmax(110px,.72fr) minmax(165px,1fr) minmax(165px,1fr);align-items:center;gap:16px}
    .expert-data-metric-head{padding:0 10px 9px;color:var(--text-muted);font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase}
    .expert-data-metric-row{padding:14px 10px;border-top:1px solid var(--border);transition:background .2s ease}.expert-data-metric-row:hover{background:rgba(77,171,247,.04)}
    .expert-data-muscle{font-weight:800;color:var(--text-primary);font-size:13px}.expert-data-sub{margin-top:4px;font-size:10px;color:var(--text-muted)}
    .expert-data-value{display:flex;justify-content:space-between;align-items:center;gap:7px;margin-bottom:7px;font-size:11px;color:var(--text-secondary)}.expert-data-value strong{font-size:14px;color:var(--text-primary)}
    .expert-data-track{height:7px;border-radius:999px;overflow:hidden;background:rgba(127,146,175,.18);box-shadow:inset 0 1px 2px rgba(0,0,0,.16)}
    .expert-data-fill{display:block;height:100%;border-radius:inherit;animation:expertDataFill .68s cubic-bezier(.22,.8,.3,1) both}@keyframes expertDataFill{from{width:0!important}}
    .expert-data-empty{padding:28px 12px;color:var(--text-muted);text-align:center;border:1px dashed var(--border);border-radius:12px;font-size:13px;line-height:1.6}
    .expert-data-form{display:grid;gap:13px}.expert-data-form label{display:block;margin-bottom:6px;color:var(--text-secondary);font-size:11px;font-weight:800;letter-spacing:.02em}.expert-data-form select,.expert-data-form input,.expert-data-form textarea{width:100%}
    .expert-data-range-wrap{padding:12px;border:1px solid var(--border);border-radius:12px;background:rgba(77,171,247,.035)}
    .expert-data-range-title{display:flex;align-items:center;justify-content:space-between;gap:10px;color:var(--text-secondary);font-size:12px;font-weight:800}.expert-data-range-score{display:inline-flex;align-items:center;justify-content:center;min-width:38px;padding:5px;border-radius:8px;background:rgba(77,171,247,.15);color:#70beff;font-size:13px}
    .expert-data-range-wrap input[type=range]{accent-color:#38bdf8;margin:12px 0 2px}.expert-data-range-labels{display:flex;justify-content:space-between;color:var(--text-muted);font-size:10px}
    .expert-data-switch{display:inline-flex!important;align-items:center;gap:10px;margin:0!important;cursor:pointer;user-select:none}.expert-data-switch input{position:absolute;opacity:0;pointer-events:none}.expert-data-switch-track{position:relative;display:inline-block;width:42px;height:23px;flex:0 0 42px;border-radius:999px;background:rgba(127,146,175,.42);box-shadow:inset 0 1px 3px rgba(0,0,0,.22);transition:background .2s ease}.expert-data-switch-track:after{content:'';position:absolute;top:3px;left:3px;width:17px;height:17px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.3);transition:transform .2s ease}.expert-data-switch input:checked + .expert-data-switch-track{background:linear-gradient(135deg,#2967c9,#30a2d8)}.expert-data-switch input:checked + .expert-data-switch-track:after{transform:translateX(19px)}.expert-data-switch input:focus-visible + .expert-data-switch-track{outline:2px solid #70beff;outline-offset:3px}.expert-data-switch-text{color:var(--text-secondary);font-size:12px;font-weight:750;letter-spacing:0}
    .expert-data-choice-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.expert-data-choice{min-height:46px;text-align:left;border:1px solid var(--border);border-radius:10px;background:transparent;color:var(--text-secondary);padding:9px 10px;font-size:12px;font-weight:700;cursor:pointer;transition:all .18s ease}.expert-data-choice:hover{border-color:#4dabf7;transform:translateY(-1px)}.expert-data-choice.selected{color:#dff5ff;border-color:#35a7e9;background:linear-gradient(135deg,rgba(42,119,210,.31),rgba(38,208,206,.14));box-shadow:inset 0 0 0 1px rgba(80,198,255,.12)}
    .expert-equipment-groups{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:start}.expert-equipment-column{display:grid;gap:12px;align-content:start;min-width:0}.expert-equipment-group{padding:12px;border:1px solid rgba(77,171,247,.18);border-radius:13px;background:linear-gradient(145deg,rgba(77,171,247,.07),rgba(10,17,31,.04));min-width:0}.expert-equipment-group-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.expert-equipment-group-head strong{color:var(--text-primary);font-size:12px}.expert-equipment-group-head span{padding:3px 7px;border-radius:999px;background:rgba(77,171,247,.13);color:#76c8ff;font-size:10px;font-weight:800}.expert-equipment-toggle-grid{display:grid;gap:7px}.expert-equipment-toggle{position:relative;display:flex!important;align-items:center;justify-content:space-between;gap:10px;min-height:52px;margin:0!important;padding:9px 10px;border:1px solid var(--border);border-radius:10px;background:rgba(7,12,23,.2);cursor:pointer;transition:border-color .18s ease,background .18s ease,transform .18s ease}.expert-equipment-toggle:hover{border-color:rgba(77,171,247,.7);background:rgba(77,171,247,.075);transform:translateY(-1px)}.expert-equipment-toggle input{position:absolute;opacity:0;pointer-events:none}.expert-equipment-copy{min-width:0}.expert-equipment-copy strong{display:block;color:var(--text-secondary);font-size:11px;font-weight:780;line-height:1.25;transition:color .18s ease}.expert-equipment-status{display:block;margin-top:3px;color:var(--text-muted);font-size:10px;font-weight:700}.expert-equipment-status:after{content:'Yok'}.expert-equipment-track{position:relative;display:inline-block;width:39px;height:22px;flex:0 0 39px;border-radius:999px;background:rgba(127,146,175,.42);box-shadow:inset 0 1px 3px rgba(0,0,0,.24);transition:background .2s ease}.expert-equipment-track:after{content:'';position:absolute;top:3px;left:3px;width:16px;height:16px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(0,0,0,.3);transition:transform .2s ease}.expert-equipment-toggle input:checked + .expert-equipment-copy strong{color:#dffaff}.expert-equipment-toggle input:checked + .expert-equipment-copy .expert-equipment-status{color:#68dfc3}.expert-equipment-toggle input:checked + .expert-equipment-copy .expert-equipment-status:after{content:'Var'}.expert-equipment-toggle input:checked ~ .expert-equipment-track{background:linear-gradient(135deg,#1972d2,#28c6a1)}.expert-equipment-toggle input:checked ~ .expert-equipment-track:after{transform:translateX(17px)}.expert-equipment-toggle input:focus-visible ~ .expert-equipment-track{outline:2px solid #70beff;outline-offset:3px}
    .expert-data-goal-intro{padding:16px;border:1px solid rgba(77,171,247,.34);border-radius:14px;background:linear-gradient(120deg,rgba(42,119,210,.18),rgba(38,208,206,.055));margin-bottom:16px}.expert-data-goal-intro h3{margin:0 0 5px;font-size:17px}.expert-data-goal-intro p{margin:0;color:var(--text-secondary)}.expert-data-profile-goal{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:11px 12px;margin:0 0 16px;border:1px solid rgba(38,208,206,.25);border-radius:12px;background:rgba(38,208,206,.055)}.expert-data-profile-goal span{display:block;color:var(--text-muted);font-size:10px;font-weight:800;letter-spacing:.05em;text-transform:uppercase}.expert-data-profile-goal strong{display:block;margin-top:3px;color:#9ee9e7;font-size:13px}.expert-data-profile-goal small{max-width:220px;color:var(--text-muted);font-size:10px;line-height:1.45;text-align:right}.expert-data-priority-heading{display:flex;align-items:end;justify-content:space-between;gap:10px;margin-bottom:8px}.expert-data-priority-heading label{margin:0!important}.expert-data-priority-count{color:#72c9ff;font-size:11px;font-weight:800}.expert-data-priority-grid .expert-data-choice{min-height:58px}.expert-data-goal-actions{margin-top:2px}
    .expert-data-summary{display:grid;gap:10px}.expert-data-summary-item{padding:11px;border:1px solid var(--border);border-radius:11px;background:rgba(77,171,247,.035)}.expert-data-summary-label{font-size:10px;font-weight:800;letter-spacing:.05em;color:var(--text-muted);text-transform:uppercase}.expert-data-summary-value{margin-top:4px;color:var(--text-primary);font-size:13px;font-weight:750;line-height:1.45}
    .expert-data-history{display:grid;gap:8px;margin-top:14px}.expert-data-history-item{padding:11px 12px;border-left:3px solid #4dabf7;border-radius:0 10px 10px 0;background:rgba(77,171,247,.05)}.expert-data-history-item strong{color:var(--text-primary);font-size:12px}.expert-data-history-item div{margin-top:4px;color:var(--text-muted);font-size:11px;line-height:1.5}
    .expert-data-doms-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.expert-data-doms-input{min-width:0;padding:11px;border:1px solid var(--border);border-radius:12px;background:rgba(77,171,247,.035);transition:border-color .18s ease,background .18s ease}.expert-data-doms-input:hover{border-color:rgba(77,171,247,.6);background:rgba(77,171,247,.06)}.expert-data-doms-input-head{display:flex;align-items:center;justify-content:space-between;gap:8px}.expert-data-doms-input-name{color:var(--text-primary);font-size:12px;font-weight:800;line-height:1.25}.expert-data-doms-input-score{display:inline-flex;align-items:center;justify-content:center;min-width:34px;padding:4px 6px;border-radius:7px;background:rgba(77,171,247,.15);color:#70beff;font-size:12px;font-weight:800}.expert-data-doms-input input[type=range]{display:block;width:100%!important;min-width:100%;max-width:100%!important;box-sizing:border-box;accent-color:#38bdf8;margin:12px 0 2px;cursor:pointer}.expert-data-doms-edit{padding:12px;border:1px solid rgba(77,171,247,.45);border-radius:12px;background:rgba(77,171,247,.06)}.expert-data-doms-edit-title{margin:0 0 4px;color:var(--text-primary);font-size:14px;font-weight:800}.expert-data-doms-edit-meta{margin:0 0 12px;color:var(--text-muted);font-size:11px}
    .expert-data-actions{display:flex;flex-wrap:wrap;gap:9px;margin-top:4px}.expert-data-danger{margin-top:16px;padding-top:16px;border-top:1px solid var(--border)}
    .expert-data-note{margin:12px 0 0;padding:10px 11px;border-radius:10px;background:rgba(255,183,3,.075);border-left:3px solid #ffb703;color:var(--text-secondary);font-size:11px;line-height:1.55}
    @media(max-width:760px){.expert-equipment-groups{grid-template-columns:1fr;gap:10px}.expert-equipment-column{gap:10px}.expert-equipment-group{padding:10px}.expert-equipment-toggle{min-height:56px;padding:10px 11px}.expert-data-actions .btn{flex:1 1 145px;min-height:42px}}
    @media(max-width:760px){.expert-data-hero{padding:18px}.expert-data-grid{grid-template-columns:1fr}.expert-data-card{padding:15px}.expert-data-metric-head{display:none}.expert-data-metric-row{grid-template-columns:1fr!important;gap:10px;padding:14px 4px}.expert-data-choice-grid,.expert-data-doms-grid,.expert-equipment-groups{grid-template-columns:1fr}.expert-data-tabs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;overflow:visible;margin-right:0}.expert-data-tab{min-width:0;justify-content:center;gap:3px;padding:9px 4px;font-size:10px;white-space:nowrap;overflow:hidden}.expert-data-tab-label{font-size:0}.expert-data-tab-label::after{content:attr(data-mobile);font-size:10px}.expert-data-subtabs{gap:6px;padding-bottom:12px;margin-bottom:14px}.expert-data-subtab{flex:1;min-width:0;padding:9px 7px;font-size:11px}.expert-data-stage{min-height:0}}
  `;
  document.head.appendChild(style);
}

function expertDataTabs() {
  const tabs = [
    ['health', 'Kas Ağrısı ve Sakatlıklar', '01', 'Sağlık'],
    ['setup', 'Hedef ve Ekipmanlar', '02', 'Tercihler'],
    ['planning', 'Split ve Analiz', '03', 'Planlama'],
  ];
  return `<nav class="expert-data-tabs" aria-label="Uzman sistemi anket sekmeleri">${tabs.map(([id, label, num, mobileLabel]) => `<button class="expert-data-tab ${expertDataTab === id ? 'active' : ''}" type="button" onclick="expertDataSwitchTab('${id}')"><span style="opacity:.72;font-size:10px">${num}</span><span class="expert-data-tab-label" data-mobile="${mobileLabel}">${label}</span></button>`).join('')}</nav>`;
}

function expertDataHealthTabs() {
  const children = [
    ['doms', 'Bugünkü Kas Ağrısı'],
    ['injuries', 'Sakatlık ve Kısıtlar'],
  ];
  return `<nav class="expert-data-subtabs" aria-label="Kas ağrısı ve sakatlık alt sekmeleri">${children.map(([id, label]) => `<button class="expert-data-subtab ${expertDataHealthTab === id ? 'active' : ''}" type="button" onclick="expertDataSwitchHealthTab('${id}')">${label}</button>`).join('')}</nav>`;
}

function expertDataSetupTabs() {
  const children = [
    ['goals', 'Hedef Kaslar'],
    ['gyms', 'Salonlar ve Ekipmanlar'],
  ];
  return `<nav class="expert-data-subtabs" aria-label="Hedef ve salon alt sekmeleri">${children.map(([id, label]) => `<button class="expert-data-subtab ${expertDataSetupTab === id ? 'active' : ''}" type="button" onclick="expertDataSwitchSetupTab('${id}')">${label}</button>`).join('')}</nav>`;
}

function expertDataPlanningTabs() {
  const children = [
    ['split', 'Split'],
    ['analysis', 'Analiz'],
  ];
  return `<nav class="expert-data-subtabs" aria-label="Split ve analiz alt sekmeleri">${children.map(([id, label]) => `<button class="expert-data-subtab ${expertDataPlanningTab === id ? 'active' : ''}" type="button" onclick="expertDataSwitchPlanningTab('${id}')">${label}</button>`).join('')}</nav>`;
}

function expertDataMetricRows() {
  const metrics = Array.isArray(expertDataState?.metrics) ? expertDataState.metrics : [];
  if (!metrics.length) return `<div class="expert-data-empty">Henüz bir kas ağrısı bildirimi yok.<br><span style="font-size:11px">Günlük durumunu sağdaki kısa formdan kaydedebilirsin.</span></div>`;
      return `<div class="expert-data-metric-head" style="grid-template-columns:minmax(110px,.72fr) minmax(165px,1fr)"><span>Kas grubu</span><span>Kas ağrısı</span></div>${metrics.map(metric => {
    const pain = Number(metric.pain_level || 0);
    return `<div class="expert-data-metric-row" style="grid-template-columns:minmax(110px,.72fr) minmax(165px,1fr)"><div><div class="expert-data-muscle">${expertDataEscape(expertDataMuscleLabel(metric.muscle_group))}</div><div class="expert-data-sub">Son günlük bildirim</div></div><div><div class="expert-data-value"><span>Bildirim seviyesi</span><strong>${pain}/5</strong></div><div class="expert-data-track"><span class="expert-data-fill" style="width:${pain * 20}%;background:${expertDataTone(pain, 'pain')}"></span></div></div></div>`;
  }).join('')}`;

}

function expertDataDomsEntries() {
  const daily = expertDataState?.doms_daily || {};
  return Object.entries(daily)
    .flatMap(([report_date, entries]) => (Array.isArray(entries) ? entries : []).map(item => ({ ...item, report_date })))
    .sort((a, b) => String(b.report_date).localeCompare(String(a.report_date)));
}

function expertDataDomsTodayEntries() {
  const entries = expertDataState?.doms_daily?.[expertDataToday()];
  return Array.isArray(entries) ? entries : [];
}

function expertDataDomsLevelInput(muscle, entry) {
  const severity = Number(entry?.severity || 0);
  const safeId = String(muscle.id).replace(/[^a-zA-Z0-9_-]/g, '');
  const muscleId = JSON.stringify(muscle.id);
  return `<div class="expert-data-doms-input"><div class="expert-data-doms-input-head"><span class="expert-data-doms-input-name">${expertDataEscape(muscle.label)}</span><span id="expertDataDomsScore_${safeId}" class="expert-data-doms-input-score">${severity}/5</span></div><input class="expertDataDomsMuscleInput" data-muscle="${expertDataEscape(muscle.id)}" data-notes="${expertDataEscape(entry?.notes || '')}" type="range" min="0" max="5" step="1" value="${severity}" oninput="expertDataDomsGridRangeChange(${muscleId}, this.value, this)" onchange="expertDataDomsGridRangeChange(${muscleId}, this.value, this)"><div class="expert-data-range-labels"><span>0 · Yok</span><span>5 · Çok yüksek</span></div></div>`;
}

function expertDataDomsEditForm(draft) {
  const safeId = String(draft.muscle_group).replace(/[^a-zA-Z0-9_-]/g, '');
  return `<div class="expert-data-doms-edit"><p class="expert-data-doms-edit-title">${expertDataEscape(expertDataMuscleLabel(draft.muscle_group))} kaydını düzenle</p><p class="expert-data-doms-edit-meta">Kayıt günü: ${expertDataEscape(expertDataDate(draft.report_date))}. Bu tarih değiştirilemez.</p><div class="expert-data-range-wrap"><div class="expert-data-range-title"><span>KAS AĞRISI SEVİYESİ</span><span id="expertDataDomsEditScore" class="expert-data-range-score">${Number(draft.severity || 0)}/5</span></div><input id="expertDataDomsEditSeverity" type="range" min="0" max="5" step="1" value="${Number(draft.severity || 0)}" oninput="expertDataDomsEditRangeChange(this.value)"><div class="expert-data-range-labels"><span>0 · Yok</span><span>5 · Çok yüksek</span></div></div><div style="margin-top:12px"><label for="expertDataDomsEditNotes">KISA NOT · İSTEĞE BAĞLI</label><textarea id="expertDataDomsEditNotes" rows="3" maxlength="500">${expertDataEscape(draft.notes || '')}</textarea></div><div class="expert-data-actions"><button class="btn btn-primary" type="button" onclick="expertDataSaveDomsEdit()">Kaydı Güncelle</button><button class="btn btn-secondary" type="button" onclick="expertDataCancelDomsEdit()">Vazgeç</button></div></div>`;
}

function expertDataDomsPane() {
  const todayEntries = expertDataDomsTodayEntries();
  const entryByMuscle = new Map(todayEntries.map(entry => [entry.muscle_group, entry]));
  const history = expertDataDomsEntries();
  const entryForm = expertDataDomsEditDraft
    ? expertDataDomsEditForm(expertDataDomsEditDraft)
    : `<div class="expert-data-doms-grid">${expertDataMuscles().map(muscle => expertDataDomsLevelInput(muscle, entryByMuscle.get(muscle.id))).join('')}</div><div class="expert-data-actions"><button class="btn btn-primary" type="button" onclick="expertDataSaveDomsGrid()">Bugünkü Ağrı Değerlerini Kaydet</button></div>`;

  const records = history.length
    ? `<div class="expert-data-history">${history.map(item => `<div class="expert-data-history-item" style="border-left-color:${expertDataTone(item.severity, 'pain')}"><strong>${expertDataEscape(expertDataMuscleLabel(item.muscle_group))} · ${Number(item.severity)}/5</strong><div>${expertDataDate(item.report_date)}${item.notes ? ` · ${expertDataEscape(item.notes)}` : ''}</div><div class="expert-data-actions" style="margin-top:8px"><button class="btn btn-secondary" style="font-size:11px;padding:6px 9px" type="button" onclick='expertDataEditDoms(${JSON.stringify(item.report_date)}, ${JSON.stringify(item.muscle_group)})'>Düzenle</button><button class="btn btn-secondary" style="font-size:11px;padding:6px 9px;color:#ef476f" type="button" onclick='expertDataDeleteDoms(${JSON.stringify(item.report_date)}, ${JSON.stringify(item.muscle_group)})'>Sil</button></div></div>`).join('')}</div>`
    : `<div class="expert-data-empty">Henüz kas ağrısı kaydı yok.</div>`;

  return `<div class="expert-data-grid"><section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>${expertDataDomsEditDraft ? 'Kas Ağrısı Kaydını Düzenle' : 'Bugünkü Kas Ağrısı Kaydı'}</h3><p>${expertDataDomsEditDraft ? 'Seçili kaydın günü korunur; yalnızca seviye ve kısa not güncellenir.' : 'Tüm kas grupları aşağıda görünür. Yalnızca ağrı hissettiğin kasların seviyesini değiştirip kaydetmen yeterlidir.'}</p></div><span class="expert-data-badge">0–5 ölçeği</span></div>${entryForm}<div class="expert-data-note"><strong>Günlük güncelleme:</strong> Kayıt günü sistem tarafından otomatik belirlenir. Aynı kası aynı gün yeniden kaydedersen eski değer güncellenir.</div></section><aside class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Kas Ağrısı Panosu</h3><p>En güncel kas ağrısı seviyesi ve kaydedilmiş bildirimlerin burada görünür.</p></div><span class="expert-data-badge">${history.length} kayıt</span></div>${expertDataMetricRows()}<div class="expert-data-note"><strong>Kayıt yönetimi:</strong> Ağrı geçtiğinde ilgili kaydı sil. Düzeltmek istediğinde kaydı düzenle.</div><div style="margin-top:16px"><div class="expert-data-summary-label">KAS AĞRISI KAYITLARI</div>${records}</div></aside></div>`;
}

function expertDataGoalsPane() {
  const priorities = expertDataMuscles().map(item => `<button type="button" class="expert-data-choice ${expertDataGoalDraft.priority_muscles.includes(item.id) ? 'selected' : ''}" onclick="expertDataTogglePriority('${item.id}')"><strong>${expertDataEscape(item.label)}</strong><span style="display:block;margin-top:3px;opacity:.7;font-size:10px">${expertDataEscape(item.ui_group || '')}</span></button>`).join('');
  const saved = expertDataState?.target_muscles || {};
  const profileGoal = expertDataProfileGoal();
  return `<div class="expert-data-grid"><section class="expert-data-card"><div class="expert-data-goal-intro"><h3>Öncelikli kaslarını seç</h3><p>Uzman sistemi, program odağını belirlemek için seçtiğin kasları kullanır. En fazla üç kas seçebilirsin.</p></div><div class="expert-data-profile-goal"><div><span>Profilinden alınan ana amaç</span><strong>${expertDataEscape(expertDataGoalLabel(profileGoal))}</strong></div><small>Genel amaç profil sayfasından yönetilir; burada tekrar girmen gerekmez.</small></div><div class="expert-data-form"><div><div class="expert-data-priority-heading"><label>ÖNCELİKLİ KASLAR</label><span class="expert-data-priority-count">${expertDataGoalDraft.priority_muscles.length}/3 seçildi</span></div><div class="expert-data-choice-grid expert-data-priority-grid">${priorities}</div></div><div><label for="expertDataGoalNote">KISA NOT · İSTEĞE BAĞLI</label><textarea id="expertDataGoalNote" rows="3" maxlength="500" placeholder="Örn. üst vücut gelişimine daha fazla odaklanmak istiyorum">${expertDataEscape(expertDataGoalDraft.priority_note || '')}</textarea></div><div class="expert-data-actions expert-data-goal-actions"><button class="btn btn-primary" type="button" onclick="expertDataSaveGoals()">Hedefleri Kaydet</button><button class="btn btn-secondary" type="button" onclick="expertDataClearGoalDraft()">Girdileri Temizle</button></div></div></section><aside class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Kaydedilen Öncelikler</h3><p>Son kaydın hesabına bağlı olarak korunur.</p></div><span class="expert-data-badge">Profil ile uyumlu</span></div><div class="expert-data-summary"><div class="expert-data-summary-item"><div class="expert-data-summary-label">Ana amaç</div><div class="expert-data-summary-value">${expertDataEscape(expertDataGoalLabel(profileGoal))}</div></div><div class="expert-data-summary-item"><div class="expert-data-summary-label">Kas öncelikleri</div><div class="expert-data-summary-value">${(saved.priority_muscles || []).length ? saved.priority_muscles.map(expertDataMuscleLabel).map(expertDataEscape).join(' · ') : 'Henüz seçilmedi'}</div></div><div class="expert-data-summary-item"><div class="expert-data-summary-label">Not</div><div class="expert-data-summary-value">${expertDataEscape(saved.priority_note || 'Not eklenmedi')}</div></div></div><div class="expert-data-danger"><button type="button" class="btn btn-secondary" style="font-size:11px;padding:7px 10px" onclick="expertDataResetLegacy()">Uzman Sistemi Verilerini Sıfırla</button><p style="margin-bottom:0">Yalnızca uzman hedefleri, kas ağrısı, salon ve sakatlık kayıtları silinir. Diğer platform verileri korunur.</p></div></aside></div>`;
}

function expertDataInjuryPane() {
  const draft = expertDataInjuryDraft || { is_active: true, severity: 0, injury_type: 'other', notes: '' };
  const activationDate = draft.started_on || expertDataToday();
  const areas = (expertDataCatalog().injury_areas || []).map(area => `<option value="${expertDataEscape(area)}" ${draft.area === area ? 'selected' : ''}>${expertDataEscape(area)}</option>`).join('');
  const types = Object.entries(expertDataCatalog().injury_types || {}).map(([id, label]) => `<option value="${expertDataEscape(id)}" ${draft.injury_type === id ? 'selected' : ''}>${expertDataEscape(label)}</option>`).join('');
  const items = (expertDataState?.injuries || []).slice().reverse();
  return `<div class="expert-data-grid"><section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>${draft.id ? 'Sakatlık Kaydını Düzenle' : 'Ağrı ve Geçici Kısıt Ekle'}</h3><p>Bu alan tıbbi tanı veya tedavi yerine geçmez. Aktif/pasif bilgisi yalnızca sakatlık kayıtları için tutulur.</p></div><span class="expert-data-badge">Kişisel bildirim</span></div><div class="expert-data-form"><div><label for="expertDataInjuryArea">BÖLGE</label><select id="expertDataInjuryArea">${areas}</select></div><div><label for="expertDataInjuryType">SAKATLIK TÜRÜ</label><select id="expertDataInjuryType">${types}</select></div><div class="expert-data-range-wrap"><div class="expert-data-range-title"><span>ETKİLENME SEVİYESİ</span><span id="expertDataInjuryScore" class="expert-data-range-score">${Number(draft.severity || 0)}/5</span></div><input id="expertDataInjurySeverity" type="range" min="0" max="5" step="1" value="${Number(draft.severity || 0)}" oninput="expertDataRangeChange('injury', this.value)"><div class="expert-data-range-labels"><span>0 · Yok</span><span>5 · Çok yüksek</span></div></div><label class="expert-data-switch" for="expertDataInjuryActive"><input id="expertDataInjuryActive" type="checkbox" ${draft.is_active !== false ? 'checked' : ''}><span class="expert-data-switch-track" aria-hidden="true"></span><span class="expert-data-switch-text">Sakatlık hâlen aktif</span></label><div><label for="expertDataInjuryActivationDate">AKTİVASYON TARİHİ</label><input id="expertDataInjuryActivationDate" type="text" value="${expertDataEscape(expertDataDate(activationDate))}" readonly aria-readonly="true" title="Bu tarih sistem tarafından otomatik belirlenir."></div><div><label for="expertDataInjuryNotes">KISA NOT · İSTEĞE BAĞLI</label><textarea id="expertDataInjuryNotes" rows="3" maxlength="500" placeholder="Örn. belirli harekette hassasiyet hissediyorum">${expertDataEscape(draft.notes || '')}</textarea></div><div class="expert-data-actions"><button class="btn btn-primary" type="button" onclick="expertDataSaveInjury()">${draft.id ? 'Kaydı Güncelle' : 'Sakatlık Kaydet'}</button>${draft.id ? '<button class="btn btn-secondary" type="button" onclick="expertDataCancelInjuryEdit()">Vazgeç</button>' : ''}</div></div><div class="expert-data-note"><strong>Otomatik takip:</strong> Kayıt aktif edildiği gün aktivasyon tarihi sistem tarafından atanır. Kaydı pasife alırsan kapanır; yeniden aktifleştirirsen aktivasyon tarihi yeni güne güncellenir.</div><div class="expert-data-note"><strong>Güvenlik notu:</strong> Keskin, olağandışı veya günlük yaşamı etkileyen ağrıda egzersizi durdurup yetkin bir sağlık uzmanına başvur.</div></section><aside class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Sakatlık Kayıtları</h3><p>Aktif ve pasif kayıtları saklanır; gerektiğinde düzenlenebilir.</p></div><span class="expert-data-badge">${items.length} kayıt</span></div>${items.length ? `<div class="expert-data-history">${items.map(item => `<div class="expert-data-history-item" style="border-left-color:${item.is_active === false ? '#7f8ea8' : expertDataTone(item.severity, 'pain')}"><strong>${expertDataEscape(item.area)} · ${expertDataEscape(expertDataCatalog().injury_types?.[item.injury_type] || 'Diğer')} · ${Number(item.severity)}/5</strong><div>${item.is_active === false ? 'Pasif' : 'Aktif'}${item.started_on ? ` · Aktivasyon: ${expertDataDate(item.started_on)}` : ''}${item.notes ? ` · ${expertDataEscape(item.notes)}` : ''}</div><div class="expert-data-actions" style="margin-top:8px"><button class="btn btn-secondary" style="font-size:11px;padding:6px 9px" type="button" onclick="expertDataEditInjury('${item.id}')">Düzenle</button>${item.is_active !== false ? `<button class="btn btn-secondary" style="font-size:11px;padding:6px 9px" type="button" onclick="expertDataResolveInjury('${item.id}')">Pasife Al</button>` : ''}<button class="btn btn-secondary" style="font-size:11px;padding:6px 9px;color:#ef476f" type="button" onclick="expertDataDeleteInjury('${item.id}')">Sil</button></div></div>`).join('')}</div>` : `<div class="expert-data-empty">Henüz sakatlık veya geçici kısıt kaydı yok.</div>`}</aside></div>`;
}

function expertDataGroupedEquipment() {
  return (expertDataCatalog().gym_equipment || []).reduce((groups, item) => {
    (groups[item.group] ||= []).push(item); return groups;
  }, {});
}

function expertDataGymsPane() {
  const draft = expertDataGymDraft || { name: '', equipment: [] };
  const selected = new Set(draft.equipment || []);
  const grouped = expertDataGroupedEquipment();
  const renderEquipmentGroup = (group, items, isContinuation = false) => `<section class="expert-equipment-group"><div class="expert-equipment-group-head"><strong>${expertDataEscape(group)}${isContinuation ? ' · devamı' : ''}</strong><span>${items.length} ekipman</span></div><div class="expert-equipment-toggle-grid">${items.map(item => `<label class="expert-equipment-toggle" for="expertEquipment_${expertDataEscape(item.id)}"><input id="expertEquipment_${expertDataEscape(item.id)}" type="checkbox" class="expertDataGymEquipment" value="${expertDataEscape(item.id)}" ${selected.has(item.id) ? 'checked' : ''}><span class="expert-equipment-copy"><strong>${expertDataEscape(item.label)}</strong><small class="expert-equipment-status" aria-live="polite"></small></span><span class="expert-equipment-track" aria-hidden="true"></span></label>`).join('')}</div></section>`;
  const equipmentColumns = [[], []];
  const columnWeights = [0, 0];
  Object.entries(grouped).forEach(([group, items]) => {
    const midpoint = Math.ceil(items.length / 2);
    const chunks = items.length > 8 ? [items.slice(0, midpoint), items.slice(midpoint)] : [items];
    chunks.forEach((chunk, index) => {
      const targetColumn = columnWeights[0] <= columnWeights[1] ? 0 : 1;
      equipmentColumns[targetColumn].push(renderEquipmentGroup(group, chunk, index > 0));
      columnWeights[targetColumn] += chunk.length + 1;
    });
  });
  const toggles = equipmentColumns.map(column => `<div class="expert-equipment-column">${column.join('')}</div>`).join('');
  const gyms = expertDataState?.gyms || [];
  return `<div class="expert-data-grid"><section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>${draft.id ? 'Salon Kaydını Düzenle' : 'Salon ve Ekipman Ekle'}</h3><p>Her salon için ekipmanın var/yok durumunu sağdaki anahtardan işaretle. Kilogram, kapasite veya çift/tek ayrıntısı istenmez.</p></div><span class="expert-data-badge">Salon bazlı</span></div><div class="expert-data-form"><div><label for="expertDataGymName">SALON ADI</label><input id="expertDataGymName" maxlength="80" value="${expertDataEscape(draft.name || '')}" placeholder="Örn. Üniversite spor salonu"></div><div><label>EKİPMAN DURUMU</label><div class="expert-equipment-groups">${toggles}</div></div><div class="expert-data-actions"><button class="btn btn-primary" type="button" onclick="expertDataSaveGym()">${draft.id ? 'Salonu Güncelle' : 'Salonu Kaydet'}</button><button class="btn btn-secondary" type="button" onclick="expertDataClearGymDraft()">Girdileri Temizle</button>${draft.id ? '<button class="btn btn-secondary" type="button" onclick="expertDataCancelGymEdit()">Vazgeç</button>' : ''}</div></div></section><aside class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Kaydedilen Salonlar</h3><p>Bir ekipmanın en az bir salonda var olması gelecekteki planlama aşaması için yeterli bilgi sağlar.</p></div><span class="expert-data-badge">${gyms.length} salon</span></div>${gyms.length ? `<div class="expert-data-history">${gyms.map(gym => { const labels = (gym.equipment || []).map(id => (expertDataCatalog().gym_equipment || []).find(item => item.id === id)?.label || id); return `<div class="expert-data-history-item"><strong>${expertDataEscape(gym.name)}</strong><div>${labels.length ? expertDataEscape(labels.join(' · ')) : 'Ekipman seçilmedi'}</div><div class="expert-data-actions" style="margin-top:8px"><button class="btn btn-secondary" style="font-size:11px;padding:6px 9px" type="button" onclick="expertDataEditGym('${gym.id}')">Düzenle</button><button class="btn btn-secondary" style="font-size:11px;padding:6px 9px;color:#ef476f" type="button" onclick="expertDataDeleteGym('${gym.id}')">Sil</button></div></div>`; }).join('')}</div>` : `<div class="expert-data-empty">Henüz salon kaydı yok.</div>`}</aside></div>`;
}

// HX_MODULAR_EXPERT_RPE_V1
function expertAnalysisTone(tone) {
  return tone === 'danger' ? '#ef476f' : tone === 'warn' ? '#ffb703' : tone === 'good' ? '#33d69f' : '#70beff';
}
function expertDataRirSummary(analysis) {
  const summary = analysis?.rpe_summary;
  if (!summary) {
    return `<section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Set Bazlı RPE</h3><p>Antrenman kaydındaki set verilerinden otomatik hesaplanır; ayrıca kullanıcıdan RPE girişi istenmez.</p></div><span class="expert-data-badge">Antrenman verisi</span></div><div class="expert-data-empty">Henüz RPE özeti oluşturacak set kaydı yok. Yeni antrenmanını kaydettiğinde sistem set bazlı çabayı otomatik olarak özetler.</div><div class="expert-data-actions"><button class="btn btn-primary" type="button" onclick="navigate('workout')">Antrenman Kaydı'na Git</button></div></section>`;
  }
  const average = expertDataEscape(summary.average_rpe ?? '—');
  const highest = expertDataEscape(summary.highest_rpe ?? '—');
  return `<section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Son RPE Özeti</h3><p>En son set verisi içeren antrenman: ${expertDataEscape(summary.workout_date_display || '—')} · ${expertDataEscape(summary.session_type || 'Antrenman')}</p></div><span class="expert-data-badge">${expertDataEscape(summary.set_count || 0)} set</span></div><div class="expert-data-history-item"><strong>Ortalama RPE: ${average}</strong><p style="margin:8px 0 0;color:var(--text-secondary)">En yüksek RPE: ${highest} · RPE 9–10 aralığındaki set: ${expertDataEscape(summary.high_effort_sets || 0)}</p></div><p style="margin:12px 0 0;color:var(--text-muted);font-size:11px;line-height:1.5">Bu özet set bazlı antrenman kaydından otomatik türetilir. RPE 9–10 çok yüksek çabayı, RPE 7–8 kontrollü zorlayıcı çabayı gösterir.</p></section>`;
}
function expertDataAnalysisDraftPane() {
  const analysis = expertAnalysisState;
  if (!analysis) return `<section class="expert-data-card"><div class="expert-data-empty">Analiz hazırlanıyor…</div></section>`;
  const status = analysis.status || {};
  const findings = (analysis.findings || []).map(item => `<div class="expert-data-history-item" style="border-left:3px solid ${expertAnalysisTone(item.tone)}"><div style="display:flex;justify-content:space-between;gap:10px"><strong>${expertDataEscape(item.title)}</strong><span class="expert-data-badge">${expertDataEscape(item.category)}</span></div><p style="margin:8px 0 5px">${expertDataEscape(item.message)}</p><small style="color:var(--text-muted)"><strong>Önerilen yaklaşım:</strong> ${expertDataEscape(item.action)}</small></div>`).join('') || '<div class="expert-data-empty">Henüz değerlendirme üretecek veri yok.</div>';
  return `<div class="expert-data-grid"><div style="display:grid;gap:18px"><section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Bugünkü Karar Merkezi</h3><p>Kısıt → toparlanma → ekipman → RPE → hedef sırasıyla çalışan açıklanabilir kurallar.</p></div><span class="expert-data-badge" style="color:${expertAnalysisTone(status.tone)}">${expertDataEscape(status.title || 'Değerlendiriliyor')}</span></div><p style="margin:0;color:var(--text-secondary);line-height:1.6">${expertDataEscape(status.message || '')}</p><p style="margin:14px 0 0;color:var(--text-muted);font-size:11px;line-height:1.5">${expertDataEscape(analysis.disclaimer || '')}</p></section><section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Kural Bulguları</h3><p>Her kart, hangi kuralın neden çalıştığını açıkça gösterir.</p></div><span class="expert-data-badge">${(analysis.findings || []).length} bulgu</span></div><div class="expert-data-history">${findings}</div></section></div><div style="display:grid;gap:18px">${expertDataRirSummary(analysis)}<section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Kural Önceliği</h3><p>Çelişen önerilerde üstteki başlık alttakini bastırır.</p></div></div><div class="expert-data-history">${(analysis.rule_order || []).map((item, index) => `<div class="expert-data-history-item"><strong>${index + 1}. ${expertDataEscape(item)}</strong></div>`).join('')}</div></section></div></div>`;
}

function expertDataRecommendation() {
  return expertDataState?.recommendation || expertRecommendationFromData(cachedUserData);
}
function expertDataSetRecommendationWeek(index) {
  const recommendation = expertDataRecommendation();
  if (!recommendation?.weeks?.length) return;
  expertRecommendationWeekIndex = Math.max(0, Math.min(recommendation.weeks.length - 1, Number(index) || 0));
  renderExpertSystem();
}
function expertDataRecommendationDayCard(day, index) {
  const exercises = Array.isArray(day?.exercises) ? day.exercises : [];
  const exerciseRows = exercises.length ? `<div style="display:grid;gap:5px;margin-top:9px">${exercises.map(item => `<div style="font-size:11px;color:var(--text-secondary);display:flex;justify-content:space-between;gap:10px"><span>${expertDataEscape(item.name)}</span><strong>${expertDataEscape(item.sets)} × ${expertDataEscape(item.reps)}</strong></div>`).join('')}</div>` : '';
  const rest = Boolean(day?.isRest) || String(day?.type || '').toLowerCase().includes('dinlenme');
  return `<article data-index="${index}" class="expert-data-history-item" style="border-left:3px solid ${rest ? '#7f8ea8' : '#4dabf7'};margin:0"><div style="display:flex;align-items:start;gap:9px"><span class="expert-recommendation-drag" title="Kaydırarak günü taşı" style="cursor:grab;color:var(--text-muted);font-size:17px;line-height:1">☰</span><div style="min-width:0;flex:1"><div style="display:flex;justify-content:space-between;gap:9px"><strong>${expertDataEscape(day?.day || `Gün ${index + 1}`)} · ${expertDataEscape(day?.type || (rest ? 'Dinlenme' : 'Antrenman'))}</strong><span class="expert-data-badge">${rest ? 'Dinlenme' : 'Seans'}</span></div><p style="margin:6px 0 0;color:var(--text-secondary)">${expertDataEscape(day?.focus || '')}</p>${day?.content_reason ? `<small style="display:block;margin-top:5px;color:var(--text-muted)">${expertDataEscape(day.content_reason)}</small>` : ''}${exerciseRows}</div></div></article>`;
}
function expertDataRecommendationPane() {
  const recommendation = expertDataRecommendation();
  if (!recommendation?.weeks?.length) {
    return `<section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Uzman Öneri Programı</h3><p>Profilindeki haftalık antrenman gün sayısı, hedef kaslar, ekipman, DOMS, aktif kısıt ve RPE özetine göre taslak oluşturur.</p></div><span class="expert-data-badge">Onaylı taslak</span></div><div class="expert-data-empty">Henüz uzman önerisi oluşturulmadı. Mevcut özel programın ve geçmiş kayıtların değişmez.</div><div class="expert-data-actions"><button class="btn btn-primary" type="button" onclick="expertDataGenerateRecommendation()">Öneri Programı Oluştur</button></div></section>`;
  }
  const safeWeek = Math.max(0, Math.min(recommendation.weeks.length - 1, expertRecommendationWeekIndex));
  const week = recommendation.weeks[safeWeek] || { days: [] };
  const tabs = recommendation.weeks.map((item, index) => `<button type="button" class="expert-data-subtab ${index === safeWeek ? 'active' : ''}" onclick="expertDataSetRecommendationWeek(${index})">${expertDataEscape(item.label || `${index + 1}. Hafta`)}</button>`).join('');
  const priority = Array.isArray(recommendation.priority_muscle_labels) && recommendation.priority_muscle_labels.length ? recommendation.priority_muscle_labels.map(expertDataEscape).join(', ') : 'Profilde seçilen öncelik yok';
  return `<section class="expert-data-card" style="grid-column:1/-1"><div class="expert-data-cardhead"><div><h3>${expertDataEscape(recommendation.name || 'Uzman Önerisi')}</h3><p>${expertDataEscape(recommendation.generated_on_display || '—')} tarihinde üretildi · profilindeki ${expertDataEscape(recommendation.days_per_week || 0)} antrenman gününe göre ${expertDataEscape(recommendation.duration_weeks || 1)} haftalık taslak.</p></div><span class="expert-data-badge">Dashboard ile senkron</span></div><div class="expert-data-history-item"><strong>Öncelikli kaslar</strong><p style="margin:6px 0 0;color:var(--text-secondary)">${priority}</p></div><div class="expert-data-subtabs" style="margin-top:14px">${tabs}</div><p style="margin:-5px 0 11px;color:var(--text-muted);font-size:11px">Günleri sol taraftaki tutamaçtan kaydırarak sırala. Düzen aynı anda Dashboard uzman önerisi kartlarına kaydedilir.</p><div id="expertRecommendationDays" style="display:grid;gap:9px">${(week.days || []).map(expertDataRecommendationDayCard).join('')}</div><div class="expert-data-actions" style="margin-top:14px"><button class="btn btn-secondary" type="button" onclick="expertDataGenerateRecommendation()">Taslağı Yenile</button></div></section>`;
}
async function expertDataGenerateRecommendation() {
  try {
    const result = await apiPost('/api/expert-data/recommendation/generate', {});
    expertDataState = expertDataState || {};
    expertDataState.recommendation = result.recommendation;
    if (cachedUserData) cachedUserData.dashboard_preferences = result.dashboard_preferences || cachedUserData.dashboard_preferences;
    expertRecommendationWeekIndex = 0;
    localStorage.setItem('selectedSplitMode', 'expert');
    toast('Uzman öneri programı oluşturuldu; Dashboard ile senkronlandı.', 'success');
    renderExpertSystem();
    refreshDashboardProgramStat('expert');
  } catch (error) { toast(error.message || 'Uzman önerisi oluşturulamadı.', 'error'); }
}
function expertDataInitRecommendationSortable() {
  const list = document.getElementById('expertRecommendationDays');
  const recommendation = expertDataRecommendation();
  if (!list || !recommendation?.weeks?.[expertRecommendationWeekIndex] || typeof Sortable === 'undefined') return;
  new Sortable(list, { handle: '.expert-recommendation-drag', animation: 180, ghostClass: 'sortable-ghost', onEnd(evt) {
    if (evt.oldIndex === evt.newIndex) return;
    const days = recommendation.weeks[expertRecommendationWeekIndex].days;
    const moved = days.splice(evt.oldIndex, 1)[0];
    days.splice(evt.newIndex, 0, moved);
    queueExpertRecommendationOrderSave(days, expertRecommendationWeekIndex);
    renderExpertSystem();
  }});
}

function expertDataSplitDraftPane() {
  const analysis = expertAnalysisState || {};
  const plan = analysis.split_plan || {};
  const focus = Array.isArray(plan.focus) && plan.focus.length ? plan.focus.map(expertDataEscape).join(', ') : 'Henüz hedef kas seçilmedi';
  const monitor = Array.isArray(plan.monitor) && plan.monitor.length ? plan.monitor.map(expertDataEscape).join(', ') : 'Özel takip gerektiren alan görünmüyor';
  const findings = (analysis.findings || []).slice(0, 4).map(item => `<div class="expert-data-history-item"><strong>${expertDataEscape(item.category || 'Kural')} · ${expertDataEscape(item.title || '')}</strong><p style="margin:7px 0 0;color:var(--text-secondary)">${expertDataEscape(item.action || '')}</p></div>`).join('') || '<div class="expert-data-empty">Analiz bulgusu bekleniyor.</div>';
  const view = `<div class="expert-data-grid"><section class="expert-data-card"><div class="expert-data-cardhead"><div><h3>${expertDataEscape(plan.title || 'Dinamik Split Yönlendirmesi')}</h3><p>Kurallar öneri programının nedenini açıklar; mevcut kişisel programı değiştirmez.</p></div><span class="expert-data-badge">Taslak yaklaşımı</span></div><div class="expert-data-history-item" style="border-left:3px solid ${expertAnalysisTone(analysis.status?.tone)}"><strong>${expertDataEscape(plan.summary || analysis.status?.title || 'Değerlendirme')}</strong><p style="margin:8px 0;color:var(--text-secondary)">${expertDataEscape(plan.approach || analysis.split_guidance || '')}</p></div><div class="expert-data-history-item"><strong>Öne çıkarılabilecek kaslar</strong><p style="margin:8px 0;color:var(--text-secondary)">${focus}</p></div><div class="expert-data-history-item"><strong>İzlenecek alanlar</strong><p style="margin:8px 0;color:var(--text-secondary)">${monitor}</p></div></section><aside class="expert-data-card"><div class="expert-data-cardhead"><div><h3>Kararın dayanağı</h3><p>Kısıt, toparlanma, ekipman, RPE ve hedef sırasıyla değerlendirilir.</p></div></div><div class="expert-data-history">${findings}</div></aside></div>${expertDataRecommendationPane()}`;
  setTimeout(expertDataInitRecommendationSortable, 0);
  return view;
}

function renderExpertSystem() {
  const content = document.getElementById('analyzeContent');
  if (!content || !expertDataState) return;
  expertDataInjectStyles();
  content.innerHTML = `<div class="expert-data-shell"><header class="expert-data-hero"><span class="expert-data-eyebrow">Uzman Sistemi · Veri ve Karar Merkezi</span><h2>Verini kaydet, kuralın nedenini gör.</h2><p>DOMS, hedef kaslar, sakatlık/kısıt, ekipman ve set bazlı RPE özeti modüler kurallarla değerlendirilir. Sistem mevcut programı otomatik değiştirmez; Split ve Analiz sekmelerinde açıklanabilir taslak yönlendirmesi sunar.</p></header>${expertDataTabs()}<div class="expert-data-stage" key="${expertDataTab}-${expertDataHealthTab}-${expertDataSetupTab}-${expertDataPlanningTab}">${expertDataPane()}</div></div>`;
}

async function loadExpertSystem() {
  const content = document.getElementById('analyzeContent');
  if (content) content.innerHTML = `<div class="card" style="padding:28px;text-align:center;color:var(--text-muted)">Uzman sistemi veri merkezi yükleniyor…</div>`;
  try {
    expertDataState = await apiGet('/api/expert-data');
    const target = expertDataState.target_muscles || {};
    expertDataGoalDraft = { primary_goal: expertDataProfileGoal(), priority_muscles: [...(target.priority_muscles || [])], priority_note: target.priority_note || '' };
    expertDataGymDraft = null;
    expertDataInjuryDraft = null;
    renderExpertSystem();
  } catch (error) {
    if (content) content.innerHTML = `<div class="card" style="padding:22px;color:var(--red)">Uzman sistemi verileri yüklenemedi: ${expertDataEscape(error.message)}</div>`;
  }
}

window.expertDataSwitchTab = function(tab) {
  if (tab === 'doms' || tab === 'injuries') {
    expertDataTab = 'health';
    expertDataHealthTab = tab;
  } else if (tab === 'goals' || tab === 'gyms') {
    expertDataTab = 'setup';
    expertDataSetupTab = tab;
  } else if (tab === 'split' || tab === 'analysis') {
    expertDataTab = 'planning';
    expertDataPlanningTab = tab;
  } else if (['health', 'setup', 'planning'].includes(tab)) {
    expertDataTab = tab;
  } else {
    return;
  }

  renderExpertSystem();
  if (expertDataTab === 'planning') expertDataLoadAnalysis();
};

window.expertDataSwitchHealthTab = function(tab) {
  if (!['doms', 'injuries'].includes(tab)) return;
  expertDataTab = 'health';
  expertDataHealthTab = tab;
  renderExpertSystem();
};
window.expertDataSwitchSetupTab = function(tab) {
  if (!['goals', 'gyms'].includes(tab)) return;
  expertDataTab = 'setup';
  expertDataSetupTab = tab;
  renderExpertSystem();
};
// HX_EXPERT_ANALYSIS_TAB_LOADING_FIX_V1
window.expertDataSwitchPlanningTab = function(tab) {
  if (!['split', 'analysis'].includes(tab)) return;
  expertDataTab = 'planning';
  expertDataPlanningTab = tab;
  renderExpertSystem();
  expertDataLoadAnalysis();
};

window.expertDataRangeChange = function(kind, value) { const id = kind === 'doms' ? 'expertDataDomsScore' : 'expertDataInjuryScore'; const label = document.getElementById(id); if (label) label.textContent = `${Number(value)}/5`; };
window.expertDataTogglePriority = function(muscle) { const items = expertDataGoalDraft.priority_muscles; if (items.includes(muscle)) expertDataGoalDraft.priority_muscles = items.filter(item => item !== muscle); else if (items.length >= 3) { toast('En fazla 3 hedef kas seçebilirsiniz.', 'error'); return; } else expertDataGoalDraft.priority_muscles = [...items, muscle]; renderExpertSystem(); };
window.expertDataClearGoalDraft = function() { expertDataGoalDraft = { primary_goal: expertDataProfileGoal(), priority_muscles: [], priority_note: '' }; renderExpertSystem(); };
window.expertDataSaveGoals = async function() { const note = document.getElementById('expertDataGoalNote')?.value || ''; if (!expertDataGoalDraft.priority_muscles.length) { toast('En az bir öncelikli kas seçin.', 'error'); return; } try { expertDataGoalDraft.primary_goal = expertDataProfileGoal(); expertDataState = await apiPut('/api/expert-data/goals', { ...expertDataGoalDraft, priority_note: note }); expertDataGoalDraft.priority_note = note; toast('Hedeflerin kaydedildi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };
window.expertDataDomsGridRangeChange = function(muscleId, value, input) {
  const level = Math.max(0, Math.min(5, Number(value) || 0));
  const safeId = String(muscleId).replace(/[^a-zA-Z0-9_-]/g, '');
  const score = document.getElementById(`expertDataDomsScore_${safeId}`);
  if (score) score.textContent = `${level}/5`;
  if (input) input.setAttribute('aria-valuetext', `${level}/5`);
};
if (!window.__expertDataDomsSliderBound) {
  document.addEventListener('input', (event) => {
    const input = event.target;
    if (input instanceof HTMLInputElement && input.classList.contains('expertDataDomsMuscleInput')) {
      window.expertDataDomsGridRangeChange(input.dataset.muscle || '', input.value, input);
    }
  });
  window.__expertDataDomsSliderBound = true;
}
window.expertDataDomsEditRangeChange = function(value) {
  const score = document.getElementById('expertDataDomsEditScore');
  if (score) score.textContent = `${Number(value)}/5`;
};
window.expertDataSaveDomsGrid = async function() {
  const existing = new Map(expertDataDomsTodayEntries().map(entry => [entry.muscle_group, entry]));
  const values = [...document.querySelectorAll('.expertDataDomsMuscleInput')].map(input => ({
    muscle_group: input.dataset.muscle,
    severity: Number(input.value || 0),
    notes: existing.get(input.dataset.muscle)?.notes || input.dataset.notes || '',
  }));
  const changedOrExisting = values.filter(item => item.severity > 0 || existing.has(item.muscle_group));
  if (!changedOrExisting.length) {
    toast('Ağrı seviyesi belirlenen en az bir kas seçin.', 'error');
    return;
  }
  try {
    for (const item of changedOrExisting) {
      expertDataState = await apiPut('/api/expert-data/doms', item);
    }
    toast('Bugünkü kas ağrısı kayıtları güncellendi.', 'success');
    renderExpertSystem();
  } catch (error) {
    toast(error.message, 'error');
  }
};
window.expertDataEditDoms = function(reportDate, muscleGroup) {
  const entries = expertDataState?.doms_daily?.[reportDate] || [];
  const item = entries.find(entry => entry?.muscle_group === muscleGroup);
  if (!item) {
    toast('Kas ağrısı kaydı bulunamadı.', 'error');
    return;
  }
  expertDataDomsEditDraft = { ...item, report_date: reportDate };
  renderExpertSystem();
};
window.expertDataCancelDomsEdit = function() {
  expertDataDomsEditDraft = null;
  renderExpertSystem();
};
window.expertDataSaveDomsEdit = async function() {
  const draft = expertDataDomsEditDraft;
  if (!draft) return;
  const payload = {
    severity: Number(document.getElementById('expertDataDomsEditSeverity')?.value || 0),
    notes: document.getElementById('expertDataDomsEditNotes')?.value || '',
  };
  try {
    expertDataState = await apiPut(`/api/expert-data/doms/${encodeURIComponent(draft.report_date)}/${encodeURIComponent(draft.muscle_group)}`, payload);
    expertDataDomsEditDraft = null;
    toast('Kas ağrısı kaydı güncellendi.', 'success');
    renderExpertSystem();
  } catch (error) {
    toast(error.message, 'error');
  }
};
window.expertDataDeleteDoms = async function(reportDate, muscleGroup) {
  if (!window.confirm(`${expertDataMuscleLabel(muscleGroup)} kas ağrısı kaydı silinsin mi?`)) return;
  try {
    expertDataState = await apiDelete(`/api/expert-data/doms/${encodeURIComponent(reportDate)}/${encodeURIComponent(muscleGroup)}`);
    if (expertDataDomsEditDraft?.report_date === reportDate && expertDataDomsEditDraft?.muscle_group === muscleGroup) expertDataDomsEditDraft = null;
    toast('Kas ağrısı kaydı silindi.', 'success');
    renderExpertSystem();
  } catch (error) {
    toast(error.message, 'error');
  }
};
window.expertDataSaveInjury = async function() { const draft = expertDataInjuryDraft || {}; const payload = { area: document.getElementById('expertDataInjuryArea')?.value, injury_type: document.getElementById('expertDataInjuryType')?.value, severity: Number(document.getElementById('expertDataInjurySeverity')?.value || 0), is_active: Boolean(document.getElementById('expertDataInjuryActive')?.checked), notes: document.getElementById('expertDataInjuryNotes')?.value || '' }; try { expertDataState = draft.id ? await apiPut(`/api/expert-data/injuries/${draft.id}`, payload) : await apiPost('/api/expert-data/injuries', payload); expertDataInjuryDraft = null; toast('Sakatlık kaydı kaydedildi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };
window.expertDataEditInjury = function(id) { const item = (expertDataState?.injuries || []).find(value => value.id === id); if (item) { expertDataInjuryDraft = { ...item }; renderExpertSystem(); } };
window.expertDataCancelInjuryEdit = function() { expertDataInjuryDraft = null; renderExpertSystem(); };
window.expertDataResolveInjury = async function(id) { const item = (expertDataState?.injuries || []).find(value => value.id === id); if (!item) return; const payload = { area: item.area, injury_type: item.injury_type, severity: Number(item.severity || 0), is_active: false, notes: item.notes || '' }; try { expertDataState = await apiPut(`/api/expert-data/injuries/${id}`, payload); toast('Sakatlık kaydı pasife alındı.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };
window.expertDataDeleteInjury = async function(id) { if (!window.confirm('Bu sakatlık kaydı silinsin mi?')) return; try { expertDataState = await apiDelete(`/api/expert-data/injuries/${id}`); toast('Sakatlık kaydı silindi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };
window.expertDataSaveGym = async function() { const draft = expertDataGymDraft || {}; const payload = { name: document.getElementById('expertDataGymName')?.value || '', equipment: [...document.querySelectorAll('.expertDataGymEquipment:checked')].map(item => item.value) }; try { expertDataState = draft.id ? await apiPut(`/api/expert-data/gyms/${draft.id}`, payload) : await apiPost('/api/expert-data/gyms', payload); expertDataGymDraft = null; toast('Salon kaydı kaydedildi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };
window.expertDataEditGym = function(id) { const item = (expertDataState?.gyms || []).find(value => value.id === id); if (item) { expertDataGymDraft = { ...item, equipment: [...(item.equipment || [])] }; renderExpertSystem(); } };
window.expertDataClearGymDraft = function() { const draft = expertDataGymDraft || {}; expertDataGymDraft = draft.id ? { ...draft, name: '', equipment: [] } : { name: '', equipment: [] }; renderExpertSystem(); toast('Salon adı ve ekipman seçimleri temizlendi.', 'info'); };
window.expertDataCancelGymEdit = function() { expertDataGymDraft = null; renderExpertSystem(); };
window.expertDataDeleteGym = async function(id) { if (!window.confirm('Bu salon kaydı silinsin mi?')) return; try { expertDataState = await apiDelete(`/api/expert-data/gyms/${id}`); toast('Salon kaydı silindi.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };
window.expertDataResetLegacy = async function() { const confirmed = window.prompt('Yalnızca bu hesaba ait uzman sistemi verilerini sıfırlamak için tam olarak şunu yazın:\nUZMAN VERİLERİNİ SIFIRLA'); if (confirmed === null) return; try { expertDataState = await apiPost('/api/expert-data/reset-legacy', { confirmation: confirmed }); expertDataGoalDraft = { primary_goal: '', priority_muscles: [], priority_note: '' }; expertDataGymDraft = null; expertDataInjuryDraft = null; expertDataDomsEditDraft = null; expertDataTab = 'health'; expertDataHealthTab = 'doms'; toast('Uzman sistemi verileri sıfırlandı. Diğer platform verileri korunmuştur.', 'success'); renderExpertSystem(); } catch (error) { toast(error.message, 'error'); } };

// Eski dinamik program ekranından kalan dashboard seçimi için güvenli geri dönüş.
const hxDataCollectionRenderSelectedSplit = renderSelectedSplit;
renderSelectedSplit = function(mode) {
  if (mode === 'expert') { toast('Uzman sistemi şu anda veri toplama aşamasındadır.', 'info'); return hxDataCollectionRenderSelectedSplit('custom'); }
  return hxDataCollectionRenderSelectedSplit(mode);
};


