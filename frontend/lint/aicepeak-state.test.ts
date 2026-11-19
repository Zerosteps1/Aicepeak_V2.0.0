// @vitest-environment node
import { RuleTester } from 'oxlint/plugins-dev'
import { describe, expect, it } from 'vitest'
import plugin from './aicepeak-state.js'

RuleTester.describe = describe
RuleTester.it = it
RuleTester.itOnly = it.only

const tester = new RuleTester({ languageOptions: { parserOptions: { lang: 'tsx' } } })
const { rules } = plugin

describe('aicepeak-state plugin', () => {
  it('registers its rules under the name aicepeak-state, each with a description', () => {
    expect(plugin.meta.name).toBe('aicepeak-state')
    expect(Object.keys(rules).sort()).toEqual([
      'context-files-only',
      'no-ref-mirror',
      'no-router-state',
      'no-state-copy-init',
      'no-sync-state-effect',
    ])
    for (const rule of Object.values(rules)) {
      expect(rule.meta.docs.description.length).toBeGreaterThan(80)
    }
  })
})

tester.run('no-state-copy-init', rules['no-state-copy-init'], {
  valid: [
    `const INITIAL = { items: [] }
     function List() { const [state] = useState(INITIAL); return state }`,
    `import { initialTheme } from './theme.ts'
     function Theme() { const [theme] = useState(initialTheme); return theme }`,
    `function Count() { const [count] = useState(0); const [items] = useState<string[]>([]); return count + items.length }`,
    `function Lazy() { const [map] = useState(() => { const fresh = new Map(); return fresh }); return map }`,
    `function Reducer() { const [state] = useReducer((s, a) => s + a, 0); return state }`,
    `function Spread() { const [state] = React.useState({ ...DEFAULTS, status: 'loading' as const }); return state }`,
    // Not a hook call inside a component: nothing to copy from.
    `const [a] = useState(window.innerWidth)`,
    // A plain function computing a fresh value is not a hook.
    `function Fresh() { const [state] = useState(() => createInitial()); return state }`,
  ],
  invalid: [
    {
      code: `function Editor({ value }: { value: string }) { const [draft] = useState(value); return draft }`,
      errors: [{ messageId: 'copy', data: { hook: 'useState', name: 'value' } }],
    },
    {
      code: `function Editor(props) { const [draft] = useState(() => props.value.trim()); return draft }`,
      errors: [{ messageId: 'copy', data: { hook: 'useState', name: 'props' } }],
    },
    {
      code: `function Copy() { const [a] = useState(1); const [b] = useState(a + 1); return b }`,
      errors: [{ messageId: 'copy', data: { hook: 'useState', name: 'a' } }],
    },
    {
      code: `function Ctx() { const auth = useContext(AuthContext); const [user] = useState(auth.user); return user }`,
      errors: [{ messageId: 'copy', data: { hook: 'useState', name: 'auth' } }],
    },
    {
      code: `function useThing(id: string) { const [state] = useReducer(reduce, { id }); return state }`,
      errors: [{ messageId: 'copy', data: { hook: 'useReducer', name: 'id' } }],
    },
    {
      code: `function Lazy({ seed }) { const [state] = useReducer(reduce, null, () => create(seed)); return state }`,
      errors: [{ messageId: 'copy', data: { hook: 'useReducer', name: 'seed' } }],
    },
    {
      code: `function Inline() { const [user] = useState(useContext(AuthContext)); return user }`,
      errors: [{ messageId: 'hookCall', data: { hook: 'useState', name: 'useContext' } }],
    },
    {
      code: `function Custom() { const [project] = useState(useProjectFlowState().project); return project }`,
      errors: [{ messageId: 'hookCall', data: { hook: 'useState', name: 'useProjectFlowState' } }],
    },
    {
      code: `function LazyHook() { const [theme] = React.useState(() => React.useContext(ThemeContext).theme); return theme }`,
      errors: [{ messageId: 'hookCall', data: { hook: 'useState', name: 'React.useContext' } }],
    },
    {
      code: `function ReducerHook() { const [state] = useReducer(reduce, use(promise)); return state }`,
      errors: [{ messageId: 'hookCall', data: { hook: 'useReducer', name: 'use' } }],
    },
  ],
})

tester.run('no-sync-state-effect', rules['no-sync-state-effect'], {
  valid: [
    `function Load() {
       const [data, setData] = useState(null)
       useEffect(() => {
         const controller = new AbortController()
         fetch('/x', { signal: controller.signal }).then((r) => r.json()).then((json) => setData(json))
         return () => controller.abort()
       }, [])
       return data
     }`,
    `function Listen() {
       const [width, setWidth] = useState(0)
       useEffect(() => {
         const onResize = () => setWidth(window.innerWidth)
         window.addEventListener('resize', onResize)
         return () => window.removeEventListener('resize', onResize)
       }, [])
       return width
     }`,
    `function Handler() { const [open, setOpen] = useState(false); return <button onClick={() => setOpen(!open)} /> }`,
    // A setter passed in, or any other function, is not this component's state.
    `function Child({ setValue }) { useEffect(() => { setValue(1) }, [setValue]); return null }`,
    `function Other() { const [a, setA] = useState(0); useEffect(() => { document.title = String(a) }, [a]); return setA }`,
    // Async functions, promise callbacks of array items and the cleanup run later.
    `function AsyncIife() {
       const [data, setData] = useState(null)
       useEffect(() => { void (async () => { setData(await load()) })() }, [])
       return data
     }`,
    `function Each({ ids }) {
       const [items, setItems] = useState([])
       useEffect(() => { ids.forEach((id) => load(id).then((item) => setItems((prev) => [...prev, item]))) }, [ids])
       return items
     }`,
    `function Cleanup() { const [on, setOn] = useState(true); useEffect(() => () => setOn(false), []); return on }`,
    // A function of the component used as a listener or event handler is not run by the effect.
    `function Named() {
       const [width, setWidth] = useState(0)
       const onResize = () => setWidth(window.innerWidth)
       useEffect(() => { window.addEventListener('resize', onResize); return () => window.removeEventListener('resize', onResize) })
       return <button onClick={onResize}>{width}</button>
     }`,
  ],
  invalid: [
    {
      code: `function Derive({ items }) {
               const [count, setCount] = useState(0)
               useEffect(() => { setCount(items.length) }, [items])
               return count
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setCount' } }],
    },
    {
      code: `function Layout() {
               const [state, dispatch] = useReducer(reduce, 0)
               useLayoutEffect(() => dispatch({ type: 'measure' }))
               return state
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'dispatch' } }],
    },
    {
      code: `function Member() {
               const [value, setValue] = React.useState(0)
               React.useEffect(() => { if (value > 1) { setValue(1) } }, [value])
               return value
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setValue' } }],
    },
    {
      code: `function ForEach({ value }) {
               const [x, setX] = useState(0)
               useEffect(() => { [value].forEach((v) => setX(v)) }, [value])
               return x
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setX' } }],
    },
    {
      code: `function Iife({ value }) {
               const [x, setX] = useState(0)
               useEffect(() => { (() => setX(value))() }, [value])
               return x
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setX' } }],
    },
    {
      code: `function Executor({ value }) {
               const [x, setX] = useState(0)
               useEffect(() => { void new Promise(() => { setX(Array.from([value], (v) => v).length) }) }, [value])
               return x
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setX' } }],
    },
    {
      code: `function ByName({ value }) {
               const [x, setX] = useState(0)
               const sync = () => { setX(value) }
               useEffect(sync, [value])
               return x
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setX' } }],
    },
    {
      code: `function Helper({ value }) {
               const [x, setX] = useState(0)
               function apply(next) { setX(next) }
               useEffect(() => { apply(value) }, [value])
               return x
             }`,
      errors: [{ messageId: 'syncSet', data: { name: 'setX' } }],
    },
  ],
})

tester.run('no-ref-mirror', rules['no-ref-mirror'], {
  valid: [
    `function Timer() { const id = useRef(0); useEffect(() => { id.current = window.setTimeout(() => {}, 10) }, []); return null }`,
    `function Flag() { const done = useRef(false); const handle = () => { done.current = true }; return handle }`,
    `function Local() { const ref = useRef(null); useEffect(() => { const controller = new AbortController(); ref.current = controller }, []); return null }`,
    // Parameters of plain functions are not props.
    `function Drag() { const last = useRef(null); const onMove = (event) => { last.current = event.clientX }; return onMove }`,
    `function Setter() { const [, setValue] = useState(0); const ref = useRef(null); ref.current = setValue; return null }`,
    `function Refs() { const a = useRef(null); const b = useRef(null); b.current = a.current; return null }`,
    // A value computed from props is not a copy of them, and useRef's initial value is a snapshot taken once.
    `function Computed({ items }) { const total = items.reduce((sum, item) => sum + item, 0); const ref = useRef(0); ref.current = total; return null }`,
    `function Snapshot({ open }) { const startedOpen = useRef(open); return startedOpen }`,
    `function SetterAlias() { const [, setValue] = useState(0); const set = setValue; const ref = useRef(null); ref.current = set; return null }`,
  ],
  invalid: [
    {
      code: `function Transition({ onDone }) { const ref = useRef(onDone); useEffect(() => { ref.current = onDone }, [onDone]); return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'onDone' } }],
    },
    {
      code: `const Panel = (props) => { const ref = useRef(null); ref.current = props.value; return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'props' } }],
    },
    {
      code: `function useLatest() { const [value] = useState(0); const ref = useRef(0); ref.current = value; return ref }`,
      errors: [{ messageId: 'mirror', data: { name: 'value' } }],
    },
    {
      code: `function Auth() { const { user } = useAuth(); const ref = useRef(null); useEffect(() => { ref.current = user }); return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'user' } }],
    },
    {
      code: `function Ctx() { const theme = useContext(ThemeContext); const ref = useRef(null); ref.current = { theme }; return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'theme' } }],
    },
    {
      code: `function Alias({ value }) { const ref = useRef(0); const v = value; ref.current = v; return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'v' } }],
    },
    {
      code: `function Hops(props) { const { user } = props; const name = user?.name; const ref = useRef(null); ref.current = name; return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'name' } }],
    },
    {
      code: `function State() { const [items] = useState([]); const count = items.length as number; const ref = useRef(0); ref.current = count; return null }`,
      errors: [{ messageId: 'mirror', data: { name: 'count' } }],
    },
  ],
})

tester.run('no-router-state', rules['no-router-state'], {
  valid: [
    `function Page() { const navigate = useNavigate(); navigate('/login', { replace: true }); return null }`,
    `function Page() { return <Link to="/projects/1">Projekt</Link> }`,
    `function Page() { return <Navigate to="/login" replace /> }`,
    // Other components may have a state prop.
    `function Page() { return <Sheet state="valid" /> }`,
    `function Page() { setState(1, { state: 2 }); return null }`,
    `function Page() { const navigate = useNavigate(); const options = { replace: true }; navigate('/login', { ...options }); return null }`,
    // Props passed through are not known here.
    `function Page(props) { return <Link {...props} to="/x" /> }`,
  ],
  invalid: [
    {
      code: `function Page() { const navigate = useNavigate(); navigate('/x', { state: { draft: 1 } }); return null }`,
      errors: [{ messageId: 'routerState' }],
    },
    {
      code: `function Page() { const go = useNavigate(); go('/x', { replace: true, 'state': 1 }); return null }`,
      errors: [{ messageId: 'routerState', data: { where: 'go(…, { state })' } }],
    },
    {
      code: `function Page() { router.navigate('/x', { state }); return null }`,
      errors: [{ messageId: 'routerState' }],
    },
    {
      code: `function Page() { return <Link to="/x" state={{ project }}>x</Link> }`,
      errors: [{ messageId: 'routerState', data: { where: '<Link state>' } }],
    },
    {
      code: `function Page() { return <><NavLink to="/x" state={1} /><Navigate to="/login" state={{ from: '/' }} /></> }`,
      errors: [
        { messageId: 'routerState', data: { where: '<NavLink state>' } },
        { messageId: 'routerState', data: { where: '<Navigate state>' } },
      ],
    },
    {
      code: `function Page() { const navigate = useNavigate(); const opts = { state: { draft: 1 } }; navigate('/x', opts); return null }`,
      errors: [{ messageId: 'routerState', data: { where: 'navigate(…, { state })' } }],
    },
    {
      code: `function Page() { const navigate = useNavigate(); const base = { state: 1 }; const opts = base; navigate('/x', { replace: true, ...opts }); return null }`,
      errors: [{ messageId: 'routerState', data: { where: 'navigate(…, { state })' } }],
    },
    {
      code: `function Page() { return <Link to="/x" {...{ state: { draft: 1 } }}>x</Link> }`,
      errors: [{ messageId: 'routerState', data: { where: '<Link {...{ state }}>' } }],
    },
    {
      code: `function Page() { const linkProps = { to: '/x', state: 1 } as const; return <NavLink {...linkProps} /> }`,
      errors: [{ messageId: 'routerState', data: { where: '<NavLink {...{ state }}>' } }],
    },
  ],
})

tester.run('context-files-only', rules['context-files-only'], {
  valid: [
    { code: `export const ThemeContext = createContext(null)`, filename: 'src/theme/themeContext.ts' },
    { code: `export const FlowContext = React.createContext(null)`, filename: 'src/features/documentUpload/projectFlowContext.ts' },
    { code: `export function Provider() { return null }`, filename: 'src/features/x/Provider.tsx' },
    { code: `import { createContext as create } from 'react'\nexport const C = create(null)`, filename: 'src/x/flowContext.ts' },
    { code: `import { createStore as createContextless } from './store.ts'\nexport const s = createContextless()`, filename: 'src/x/store.ts' },
  ],
  invalid: [
    {
      code: `export const ThemeContext = createContext(null)`,
      filename: 'src/theme/ThemeProvider.tsx',
      errors: [{ messageId: 'place' }],
    },
    {
      code: `const Local = React.createContext(0)`,
      filename: 'src/features/x/state.ts',
      errors: [{ messageId: 'place' }],
    },
    {
      code: `export const C = createContext(null)`,
      filename: 'src/features/x/fooContext.tsx',
      errors: [{ messageId: 'place' }],
    },
    {
      code: `import { createContext as cc } from 'react'\nexport const Other = cc(null)`,
      filename: 'src/features/x/Provider.tsx',
      errors: [{ messageId: 'place' }],
    },
  ],
})
