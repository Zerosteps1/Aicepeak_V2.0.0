/* @ds-bundle: {"format":4,"namespace":"AicepeakPaperGlass","components":[{"name":"GlassBar"},{"name":"AssistantPanel"},{"name":"AssistantMessage"},{"name":"UserMessage"},{"name":"AssistantItem"},{"name":"Button"},{"name":"IconButton"},{"name":"PageHeader"},{"name":"Tabs"},{"name":"KpiStrip"},{"name":"DataTable"},{"name":"LineItemName"},{"name":"Delta"},{"name":"TopicsLink"},{"name":"DotMatrix"},{"name":"StatusTag"},{"name":"ProjectMark"},{"name":"ProjectTiles"},{"name":"ProjectTile"},{"name":"SignInCard"},{"name":"Icon"}]} */
(function () {
  var React = window.React;
  var h = React.createElement;
  var Fragment = React.Fragment;

  function cx() {
    var out = [];
    for (var i = 0; i < arguments.length; i++) if (arguments[i]) out.push(arguments[i]);
    return out.join(' ');
  }
  function omit(obj, keys) {
    var out = {};
    for (var k in obj) if (Object.prototype.hasOwnProperty.call(obj, k) && keys.indexOf(k) < 0) out[k] = obj[k];
    return out;
  }

  /* Numbers: thousands with a space, true minus, signed deltas. */
  function formatNumber(n) {
    var s = String(Math.abs(Math.round(n))).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
    return (n < 0 ? '−' : '') + s;
  }
  function formatDelta(n) {
    if (n === 0) return '±0';
    return (n > 0 ? '+' : '−') + formatNumber(Math.abs(n));
  }

  /* Icons: stroke-only, currentColor. */
  var ICONS = {
    documents: { w: 1.6, d: ['M8 7V4h9l3 3v11h-4', 'M4 8h10l2 2v10H4z'] },
    positions: { w: 1.6, rect: true, d: ['M4 9.5h16M4 14.5h16'] },
    topics: { w: 1.6, dot: true, d: ['M8.5 8.5a5 5 0 0 0 0 7M15.5 8.5a5 5 0 0 1 0 7M6 6a8.5 8.5 0 0 0 0 12M18 6a8.5 8.5 0 0 1 0 12'] },
    bell: { w: 1.6, d: ['M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z', 'M10 20.5h4'] },
    chat: { w: 1.6, d: ['M4 5h16v11H9l-5 4z'] },
    search: { w: 1.8, d: ['M20 20l-4.5-4.5'], circle: [11, 11, 6] },
    close: { w: 1.6, d: ['M6 6l12 12M18 6L6 18'] },
    send: { w: 2, d: ['M5 12h13M13 6l6 6-6 6'] },
    status: { w: 1.6, circle: [12, 12, 9], center: true, d: [] },
    check: { w: 2, d: ['M5 12.5l4.5 4.5L19 7.5'] },
    link: { w: 1.8, d: ['M9 8H7a4 4 0 0 0 0 8h2M15 8h2a4 4 0 0 1 0 8h-2M8 12h8'] },
    arrow: { w: 2, d: ['M5 12h13M13 6l6 6-6 6'] },
    plus: { w: 1.6, d: ['M12 5v14M5 12h14'] },
    chevron: { w: 1.6, d: ['M6 9l6 6 6-6'] },
    'sign-out': { w: 1.6, d: ['M14 4h5v16h-5', 'M10 8l-4 4 4 4M6 12h10'] }
  };
  function Icon(props) {
    var def = ICONS[props.name];
    if (!def) return null;
    var size = props.size || 18;
    var kids = [];
    if (def.rect) kids.push(h('rect', { key: 'r', x: 4, y: 4, width: 16, height: 16, rx: 2 }));
    if (def.circle) kids.push(h('circle', { key: 'c', cx: def.circle[0], cy: def.circle[1], r: def.circle[2] }));
    if (def.dot) kids.push(h('circle', { key: 'd', cx: 12, cy: 12, r: 1.6 }));
    if (def.center) kids.push(h('circle', { key: 'm', cx: 12, cy: 12, r: 1.5, fill: 'currentColor' }));
    def.d.forEach(function (d, i) { kids.push(h('path', { key: i, d: d })); });
    return h('svg', { 'aria-hidden': 'true', width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: def.w, className: props.className, style: props.style }, kids);
  }

  /* Buttons */
  function Button(props) {
    var variant = props.variant || 'glass';
    var rest = omit(props, ['variant', 'icon', 'dot', 'children', 'className', 'type']);
    return h('button', Object.assign({ type: props.type || 'button', className: cx('pg-btn', 'pg-btn--' + variant, props.className) }, rest),
      props.dot ? h('span', { className: 'pg-dot', 'aria-hidden': 'true' }) : null,
      props.children,
      props.icon ? h(Icon, { name: props.icon, size: 16 }) : null);
  }
  function IconButton(props) {
    var rest = omit(props, ['icon', 'label', 'surface', 'className', 'size']);
    return h('button', Object.assign({ type: 'button', 'aria-label': props.label, title: props.label, className: cx('pg-icon-btn', props.surface === 'paper' && 'pg-icon-btn--paper', props.className) }, rest),
      h(Icon, { name: props.icon, size: props.size || (props.icon === 'bell' ? 20 : 18) }));
  }

  /* Glass top bar */
  function GlassBar(props) {
    var nav = props.nav || [];
    var crumbs = props.breadcrumbs || [];
    return h('header', { className: cx('pg-glass', props.glass === 'airy' && 'pg-glass--airy', 'pg-bar', props.className), style: props.style },
      h('div', { className: 'pg-bar__start' },
        props.logoSrc ? h('img', { className: 'pg-bar__logo', src: props.logoSrc, alt: props.logoAlt || 'Aicepeak' }) : null,
        h('nav', { className: 'pg-nav', 'aria-label': 'Hauptnavigation' },
          nav.map(function (item, i) {
            return h('a', { key: i, className: 'pg-nav__item', href: item.href || '#', 'aria-current': item.current ? 'page' : undefined, onClick: item.onClick },
              item.icon ? h(Icon, { name: item.icon }) : null, item.label);
          })),
        crumbs.length ? h('span', { className: 'pg-bar__divider', 'aria-hidden': 'true' }) : null,
        crumbs.length ? h('nav', { className: 'pg-crumbs', 'aria-label': 'Pfad' },
          crumbs.map(function (c, i) {
            var last = i === crumbs.length - 1;
            return h(Fragment, { key: i },
              i > 0 ? h('span', { 'aria-hidden': 'true' }, '/') : null,
              last ? h('span', { 'aria-current': 'page' }, c.label) : h('a', { href: c.href || '#' }, c.label));
          })) : null),
      h('div', { className: 'pg-bar__end' }, props.actions));
  }

  /* Assistant */
  function AssistantPanel(props) {
    var suggestions = props.suggestions || [];
    var inputId = props.inputId || 'pg-assistant-input';
    var collapsible = !!props.collapsible;
    var expanded = collapsible ? !!props.expanded : true;
    var bodyId = inputId + '-body';
    var titles = h('span', { style: { display: 'flex', flexDirection: 'column', gap: 3 } },
      h('span', { className: 'pg-assistant__title panel-title' }, h('span', { className: 'pg-dot', 'aria-hidden': 'true' }), props.title || 'Assistent'),
      props.context ? h('span', { className: 'pg-assistant__ctx' }, props.context) : null);
    var head = collapsible
      ? h('button', { type: 'button', className: 'pg-assistant__toggle', 'aria-expanded': expanded ? 'true' : 'false', 'aria-controls': bodyId, onClick: props.onToggle },
          titles, h('span', { className: 'pg-assistant__chevron', 'aria-hidden': 'true' }, h(Icon, { name: 'chevron' })))
      : h('div', { className: 'pg-assistant__head' }, titles,
          props.onClose !== null ? h(IconButton, { icon: 'close', label: 'Chat schließen', onClick: props.onClose }) : null);
    return h('section', { className: cx('pg-glass', props.glass === 'airy' && 'pg-glass--airy', 'pg-assistant', collapsible && 'pg-assistant--collapsible', !expanded && 'pg-assistant--collapsed', props.className), style: props.style, 'aria-label': props.title || 'Assistent' },
      head,
      h('div', { className: 'pg-assistant__inner', id: bodyId, 'aria-hidden': expanded ? undefined : 'true', inert: expanded ? undefined : '' },
      h('div', { className: 'pg-assistant__body' }, props.children),
      suggestions.length ? h('div', { className: 'pg-chips' }, suggestions.map(function (s, i) {
        return h('button', { key: i, type: 'button', className: 'pg-chip', onClick: props.onSuggestion ? function () { props.onSuggestion(s); } : undefined }, s);
      })) : null,
      h('form', { className: 'pg-composer', onSubmit: function (e) { e.preventDefault(); if (props.onSend) props.onSend(e.target.elements[inputId].value); } },
        h('label', { htmlFor: inputId, className: 'pg-sr' }, 'Nachricht an den Assistenten'),
        h('input', { id: inputId, name: inputId, type: 'text', placeholder: props.placeholder || 'Frage stellen …' }),
        h('button', { type: 'submit', className: 'pg-send', 'aria-label': 'Senden' }, h(Icon, { name: 'send' })))));
  }
  function AssistantMessage(props) {
    return h('div', { className: 'pg-msg' }, props.children,
      props.sources ? h('span', { className: 'pg-msg__sources' }, props.sources) : null);
  }
  function UserMessage(props) {
    return h('div', { className: 'pg-bubble' }, props.children);
  }
  function AssistantItem(props) {
    return h('a', { className: 'pg-item', href: props.href || '#', onClick: props.onClick }, h('span', null, props.label), h('span', null, props.note));
  }

  /* Page header */
  function PageHeader(props) {
    return h('div', { className: cx('pg-head', props.className) },
      h('div', { className: 'pg-head__main' },
        props.eyebrow ? h('span', { className: 'eyebrow', style: { color: 'var(--ink-muted)' } }, props.eyebrow) : null,
        h('h1', { className: 'pg-head__title page-title' }, props.title, h('span', { className: 'pg-stop' }, '.')),
        props.meta ? h('p', { className: 'label', style: { margin: 0, color: 'var(--ink-muted)' } }, props.meta) : null),
      (props.status || props.action) ? h('div', { className: 'pg-head__aside' },
        props.status ? h('span', { className: 'pg-status' }, props.statusIcon !== false ? h(Icon, { name: 'status', size: 16, style: { color: 'var(--review)' } }) : null, props.status) : null,
        props.action) : null);
  }

  /* Tabs */
  function Tabs(props) {
    var items = props.items || [];
    return h('div', { className: 'pg-tabs', role: 'tablist', 'aria-label': props.label || 'Berichtsteil', style: { gridTemplateColumns: 'repeat(' + Math.max(items.length, 1) + ', minmax(0, 1fr))' } },
      items.map(function (it, i) {
        return h('button', { key: i, type: 'button', role: 'tab', className: 'pg-tab', 'aria-selected': it.selected ? 'true' : 'false', onClick: props.onSelect ? function () { props.onSelect(i, it); } : undefined },
          it.count != null ? h('span', { className: 'pg-tab__count' }, it.count) : null, it.label);
      }));
  }

  /* KPI strip */
  function KpiStrip(props) {
    var base = props.base || {}, sig = props.signal || {};
    return h('div', { className: 'pg-kpi' },
      h('span', { className: 'pg-kpi__frame', 'aria-hidden': 'true' }),
      h('div', { className: 'pg-kpi__tile pg-kpi__tile--base' },
        h('span', { className: 'pg-kpi__label' }, base.label),
        h('span', { className: 'pg-kpi__value kpi-value pg-num' }, typeof base.value === 'number' ? formatNumber(base.value) : base.value)),
      h('div', { className: 'pg-kpi__tile pg-kpi__tile--signal' },
        props.bleed !== false ? h('span', { className: 'pg-kpi__band', 'aria-hidden': 'true' }) : h('span', { className: 'pg-kpi__band', 'aria-hidden': 'true', style: { width: '100%' } }),
        h('span', { className: 'pg-kpi__label' }, sig.label),
        h('span', { className: 'pg-kpi__value' },
          sig.delta != null ? h('span', { className: 'pg-kpi__delta' }, typeof sig.delta === 'number' ? formatDelta(sig.delta) : sig.delta) : null,
          h('span', { className: 'kpi-value pg-num' }, typeof sig.value === 'number' ? formatNumber(sig.value) : sig.value, sig.unit ? h('span', { className: 'pg-kpi__unit' }, ' ' + sig.unit) : null))));
  }

  /* Table pieces */
  function LineItemName(props) {
    return h('span', { className: 'pg-name' }, h('a', { href: props.href || '#', onClick: props.onClick }, props.children));
  }
  function Delta(props) {
    var v = props.value;
    return h('span', { className: v > 0 ? 'pg-pos' : (v < 0 ? 'pg-neg' : 'pg-zero') }, formatDelta(v));
  }
  function TopicsLink(props) {
    var topics = props.topics || [];
    if (!topics.length) return h('span', { style: { color: 'var(--ink-subtle)', fontSize: 13 } }, '–');
    return h('a', { className: 'pg-topics', href: props.href || '#', onClick: props.onClick, 'aria-label': topics.length + (topics.length === 1 ? ' Thema: ' : ' Themen: ') + topics.join(', ') },
      h(Icon, { name: 'link', size: 16 }), String(topics.length));
  }
  function StatusTag(props) {
    if (props.status === 'review') return h('span', { className: 'pg-tag pg-tag--review' }, props.children || 'Rückfrage');
    if (props.status === 'running') return h('span', { className: 'pg-tag pg-tag--running' }, props.children || 'Läuft');
    return h('span', { className: 'pg-tag pg-tag--done' }, h(Icon, { name: 'check', size: 14 }), props.children || 'Geprüft');
  }

  /* Dot matrix: N x N, columns light bottom-up between the series' min and max. */
  function DotMatrix(props) {
    var values = props.values || [];
    var n = Math.min(6, Math.max(3, props.size || values.length || 4));
    var abs = values.slice(0, n).map(function (v) { return Math.abs(v); });
    while (abs.length < n) abs.push(abs.length ? abs[abs.length - 1] : 0);
    var lo = Math.min.apply(null, abs), hi = Math.max.apply(null, abs);
    var level = abs.map(function (v) { return hi === lo ? n : 1 + Math.round((n - 1) * (v - lo) / (hi - lo)); });
    var dots = [];
    for (var row = 0; row < n; row++) for (var col = 0; col < n; col++) dots.push(h('i', { key: row + '-' + col, className: level[col] >= n - row ? 'on' : undefined }));
    var matrix = h('span', { className: 'pg-matrix', 'aria-hidden': 'true', style: { gridTemplateColumns: 'repeat(' + n + ', 5px)' } }, dots);
    return props.label ? h('span', { role: 'img', 'aria-label': props.label, style: { display: 'inline-flex' } }, matrix) : matrix;
  }

  /* Data table: columns [{key,label,sub,numeric,highlight,width}], rows [{key,selected,cells:{}}], total {cells:{}} */
  function DataTable(props) {
    var columns = props.columns || [];
    var grid = columns.map(function (c) { return c.width || 'minmax(84px, 1fr)'; }).join(' ');
    var titleId = props.id || 'pg-table-title';
    function cell(c, i, content, head) {
      var cls = cx('pg-cell', i === 0 && 'pg-cell--first', c.numeric && 'pg-cell--num', c.highlight && 'pg-cell--hl');
      var style = c.numeric && !c.highlight ? { textAlign: 'right' } : undefined;
      return h('span', { key: c.key, role: head ? 'columnheader' : 'cell', className: cls, style: style }, content);
    }
    var search = props.search;
    var searchId = titleId + '-search';
    var searchHead = search ? h('div', { role: 'search', className: 'pg-table__search', style: { minWidth: props.minWidth || 820 } },
      h('label', { htmlFor: searchId, className: 'pg-sr' }, search.label || search.placeholder || 'Suchen'),
      h(Icon, { name: 'search', size: 20 }),
      h('span', { className: 'pg-table__cursor', 'aria-hidden': 'true' }),
      h('input', { id: searchId, type: 'text', autoComplete: 'off', placeholder: search.placeholder || 'Suchen …', value: search.onChange ? (search.value || '') : undefined, defaultValue: search.onChange ? undefined : search.value, onChange: search.onChange ? function (e) { search.onChange(e.target.value); } : undefined }),
      search.hint ? h('span', { className: 'pg-table__hint' }, search.hint) : null,
      search.count != null ? h('span', { className: 'pg-table__sep', 'aria-hidden': 'true' }) : null,
      search.count != null ? h('span', { className: 'pg-table__count', 'aria-live': 'polite' }, search.count) : null) : null;
    return h('section', { className: 'pg-table', 'aria-labelledby': search ? undefined : titleId, 'aria-label': search ? (props.title || search.label) : undefined },
      searchHead,
      (!search && (props.title || props.tools)) ? h('div', { className: 'pg-table__head' },
        h('div', { className: 'pg-table__titles' },
          h('h2', { id: titleId, className: 'pg-table__title section-title' }, props.title),
          props.description ? h('span', { className: 'pg-table__desc' }, props.description) : null),
        h('span', { className: 'pg-table__tools' },
          props.unit ? h('span', { className: 'label', style: { color: 'var(--ink-muted)' } }, props.unit) : null,
          props.onSearch !== null ? h(IconButton, { icon: 'search', label: props.searchLabel || 'Suchen', surface: 'paper', onClick: props.onSearch }) : null)) : null,
      h('div', { role: 'table', 'aria-labelledby': search ? undefined : titleId, 'aria-label': search ? (props.title || search.label) : undefined, style: { minWidth: props.minWidth || 820 } },
        h('div', { role: 'row', className: 'pg-row pg-row--head', style: { gridTemplateColumns: grid } },
          columns.map(function (c, i) {
            return cell(c, i, h(Fragment, null, c.label, c.sub ? h('span', { className: 'pg-cell__sub' }, c.sub) : null), true);
          })),
        (props.rows || []).map(function (r, ri) {
          return h('div', { key: r.key || ri, role: 'row', className: cx('pg-row', r.selected && 'pg-row--selected'), style: { gridTemplateColumns: grid }, onClick: r.onClick },
            columns.map(function (c, i) { return cell(c, i, r.cells[c.key]); }));
        }),
        props.total ? h('div', { role: 'row', className: 'pg-row pg-row--total', style: { gridTemplateColumns: grid } },
          columns.map(function (c, i) { return cell(c, i, props.total.cells[c.key]); })) : null));
  }

  /* Project mark: a stable 4x4 shape from the project's ID plus one real figure.
     Shape: left half from an FNV-1a hash of the ID (3-6 dots), mirrored right; never changes.
     Fill: the EBITDA result on a log scale (10 k€ none, 10 M€ all) sets how many shape dots are full,
     bottom-up in mirrored pairs; the rest of the shape is half. Blue positive, red negative. */
  function markHash(str, salt) {
    var x = (2166136261 ^ salt) >>> 0;
    for (var i = 0; i < str.length; i++) { x ^= str.charCodeAt(i); x = Math.imul(x, 16777619); }
    return x >>> 0;
  }
  function markShape(id) {
    for (var salt = 0; salt < 64; salt++) {
      var bits = markHash(String(id), salt) & 255, n = 0;
      for (var k = 0; k < 8; k++) n += (bits >> k) & 1;
      if (n >= 3 && n <= 6) return bits;
    }
    return 0x5a;
  }
  function ProjectMark(props) {
    var bits = markShape(props.id || '');
    var order = [];
    for (var r = 3; r >= 0; r--) for (var c = 0; c < 2; c++) if ((bits >> (r * 2 + c)) & 1) order.push(r * 2 + c);
    var v = Math.abs((props.value || 0) * 1000);
    var f = v > 10000 ? Math.min(1, Math.log(v / 10000) / Math.LN10 / 3) : 0;
    var full = Math.round(f * order.length);
    var state = {};
    order.forEach(function (k, i) { state[k] = i < full ? 'full' : 'half'; });
    var dots = [];
    for (var row = 0; row < 4; row++) for (var col = 0; col < 4; col++) {
      var k = row * 2 + (col < 2 ? col : 3 - col);
      dots.push(h('i', { key: row + '-' + col, className: state[k] }));
    }
    var label = props.label || ('EBITDA-Ergebnis ' + formatNumber(props.value || 0) + ' T€');
    return h('span', { role: 'img', 'aria-label': label, className: cx('pg-mark', (props.value || 0) < 0 && 'pg-mark--neg', props.onSignal && 'pg-mark--on-signal', props.className) }, dots);
  }

  /* Project tiles: the last projects to continue with; the first (most recent) is highlighted. */
  function ProjectTiles(props) {
    return h('div', { className: 'pg-tiles', style: { gridTemplateColumns: 'repeat(' + React.Children.count(props.children) + ', minmax(0, 1fr))' } }, props.children);
  }
  function ProjectTile(props) {
    var hot = !!props.highlight;
    return h('a', { className: cx('pg-tile', hot && 'pg-tile--hot'), href: props.href || '#', onClick: props.onClick },
      h('span', { className: 'pg-tile__top' },
        h('span', null, props.opened),
        h('span', { className: 'pg-tile__arrow', 'aria-hidden': 'true' }, h(Icon, { name: 'arrow', size: 16 }))),
      h('span', { className: 'pg-tile__titles' },
        h('span', { className: 'pg-tile__title' }, props.title),
        props.note ? h('span', { className: 'pg-tile__note' }, props.note) : null),
      h('span', { className: 'pg-tile__bottom' },
        h('span', null, props.status ? h(StatusTag, { status: props.status }, props.statusText) : null),
        h('span', { className: 'pg-tile__figure' },
          props.value != null ? h('span', { className: 'pg-tile__value' }, typeof props.value === 'number' ? formatNumber(props.value) : props.value,
            props.unit ? h('span', { className: 'pg-tile__unit' }, ' ' + props.unit) : null) : null,
          props.mark ? h(ProjectMark, Object.assign({}, props.mark, { onSignal: hot })) : null)));
  }

  /* Sign-in card */
  function SignInCard(props) {
    var busy = !!props.busy;
    return h('form', { className: cx('pg-signin', props.className), style: props.style, role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'pg-signin-title',
      onSubmit: function (e) { e.preventDefault(); if (!busy && props.onSignIn) props.onSignIn(e); } },
      props.logoSrc ? h('img', { className: 'pg-signin__logo', src: props.logoSrc, alt: props.logoAlt || 'Aicepeak' }) : null,
      h('h1', { id: 'pg-signin-title', className: 'pg-signin__title sign-in-title' }, props.title || 'Anmelden', h('span', { className: 'pg-stop' }, '.')),
      h('button', { type: 'submit', className: 'pg-signin__btn', 'aria-busy': busy ? 'true' : undefined },
        h('span', null, busy ? (props.busyLabel || 'Anmeldung läuft …') : (props.buttonLabel || 'Mit Microsoft anmelden')),
        h('span', { className: 'pg-signin__arrow', 'aria-hidden': 'true' }, h(Icon, { name: 'arrow' }))),
      props.note ? h('p', { className: 'pg-signin__note' }, props.note) : null);
  }

  window.AicepeakPaperGlass = {
    GlassBar: GlassBar,
    AssistantPanel: AssistantPanel,
    AssistantMessage: AssistantMessage,
    UserMessage: UserMessage,
    AssistantItem: AssistantItem,
    Button: Button,
    IconButton: IconButton,
    PageHeader: PageHeader,
    Tabs: Tabs,
    KpiStrip: KpiStrip,
    DataTable: DataTable,
    LineItemName: LineItemName,
    Delta: Delta,
    TopicsLink: TopicsLink,
    DotMatrix: DotMatrix,
    StatusTag: StatusTag,
    ProjectMark: ProjectMark,
    ProjectTiles: ProjectTiles,
    ProjectTile: ProjectTile,
    SignInCard: SignInCard,
    Icon: Icon,
    formatNumber: formatNumber,
    formatDelta: formatDelta
  };
})();
