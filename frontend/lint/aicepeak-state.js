// Oxlint JS plugin (ESLint-compatible rule objects) that keeps React state in one place: a provider holds it, and
// components read it through hooks and call plain action functions. Nothing is copied into a second place.
// Registered in .oxlintrc.json via `jsPlugins`; tested in aicepeak-state.test.ts.

const STATE_HOOKS = new Set(['useState', 'useReducer'])
const EFFECT_HOOKS = new Set(['useEffect', 'useLayoutEffect', 'useInsertionEffect'])
/** Hooks whose result is not a copy of props, state or context. */
const REF_LIKE_HOOKS = new Set(['useRef', 'useId'])
const ROUTER_LINKS = new Set(['Link', 'NavLink', 'Navigate'])
const FUNCTION_TYPES = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'])
/** TypeScript wrappers around an expression; only their `expression` is a value. */
const TS_EXPRESSIONS = new Set([
  'TSAsExpression',
  'TSSatisfiesExpression',
  'TSNonNullExpression',
  'TSTypeAssertion',
  'TSInstantiationExpression',
])

/** `useState` for `useState(…)` and `React.useState(…)`; `null` for other callees. */
function calleeName(call) {
  const callee = call.callee
  if (callee.type === 'Identifier') {
    return callee.name
  }
  if (callee.type === 'MemberExpression' && !callee.computed && callee.property.type === 'Identifier') {
    return callee.property.name
  }
  return null
}

function isHookName(name) {
  return name === 'use' || /^use[A-Z0-9]/.test(name)
}

function isWithin(inner, outer) {
  return inner.range[0] >= outer.range[0] && inner.range[1] <= outer.range[1]
}

function enclosingFunction(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (FUNCTION_TYPES.has(current.type)) {
      return current
    }
  }
  return null
}

/** The name a function is known by: its own, the variable it is assigned to, or that of a wrapping call (`memo`). */
function functionName(fn) {
  if (fn.id) {
    return fn.id.name
  }
  let parent = fn.parent
  if (parent?.type === 'CallExpression') {
    parent = parent.parent
  }
  return parent?.type === 'VariableDeclarator' && parent.id.type === 'Identifier' ? parent.id.name : null
}

/** Components are named in PascalCase, hooks `use…`. */
function isComponentOrHook(fn) {
  const name = functionName(fn)
  return name !== null && (/^[A-Z]/.test(name) || isHookName(name))
}

/** The variable an identifier refers to, looked up by name from its scope outwards; `null` for globals. */
function resolve(sourceCode, identifier) {
  for (let scope = sourceCode.getScope(identifier); scope; scope = scope.upper) {
    const variable = scope.set.get(identifier.name)
    if (variable) {
      return variable
    }
  }
  return null
}

/** `node` without the TypeScript wrappers around it (`x as T`, `x!`, `x satisfies T`, …). */
function unwrapTs(node) {
  let current = node
  while (current && TS_EXPRESSIONS.has(current.type)) {
    current = current.expression
  }
  return current
}

/**
 * Calls `visit` for `node` and every node below it in value position: no non-computed member properties or object
 * keys, no types.
 */
function walkValues(sourceCode, node, visit) {
  if (!node || typeof node.type !== 'string') {
    return
  }
  if (node.type.startsWith('TS')) {
    if (TS_EXPRESSIONS.has(node.type)) {
      walkValues(sourceCode, node.expression, visit)
    }
    return
  }
  visit(node)
  for (const key of sourceCode.visitorKeys[node.type] ?? []) {
    if (key === 'typeAnnotation' || key === 'typeArguments' || key === 'typeParameters' || key === 'returnType') {
      continue
    }
    if (key === 'property' && node.type === 'MemberExpression' && !node.computed) {
      continue
    }
    if (key === 'key' && !node.computed && (node.type === 'Property' || node.type === 'PropertyDefinition' || node.type === 'MethodDefinition')) {
      continue
    }
    const child = node[key]
    if (Array.isArray(child)) {
      child.forEach((item) => walkValues(sourceCode, item, visit))
    } else {
      walkValues(sourceCode, child, visit)
    }
  }
}

/**
 * Every identifier in value position below `node` (see `walkValues`). Identifiers that declare something inside
 * `node` are included; callers tell them apart by where they resolve.
 */
function valueIdentifiers(sourceCode, node) {
  const found = []
  walkValues(sourceCode, node, (child) => {
    if (child.type === 'Identifier') {
      found.push(child)
    }
  })
  return found
}

/** Every call of a hook (`useX(…)`, `React.useX(…)`, `use(…)`) in value position below `node`, `node` included. */
function hookCalls(sourceCode, node) {
  const found = []
  walkValues(sourceCode, node, (child) => {
    if (child.type === 'CallExpression' && isHookName(calleeName(child) ?? '')) {
      found.push(child)
    }
  })
  return found
}

/** The `useState`/`useReducer` call that a destructuring `const [value, setValue] = …` takes `variable` from. */
function stateHookDeclaration(variable) {
  const def = variable.defs[0]
  if (def?.type !== 'Variable' || def.node.type !== 'VariableDeclarator') {
    return null
  }
  const init = def.node.init
  if (init?.type !== 'CallExpression' || !STATE_HOOKS.has(calleeName(init) ?? '')) {
    return null
  }
  return { declarator: def.node, name: def.name }
}

/** Whether `variable` is the setter (second element) of `const [value, setValue] = useState(…)`. */
function isStateSetter(variable) {
  const declaration = stateHookDeclaration(variable)
  const pattern = declaration?.declarator.id
  const setter = pattern?.type === 'ArrayPattern' ? pattern.elements[1] : null
  return setter?.type === 'Identifier' && setter.range[0] === declaration.name.range[0]
}

/** The identifier a plain read starts from: `a` for `a`, `a.b.c`, `a?.b` or `a[i]`; `null` for anything computed. */
function readRoot(node) {
  let current = unwrapTs(node)
  while (current?.type === 'MemberExpression' || current?.type === 'ChainExpression') {
    current = unwrapTs(current.type === 'ChainExpression' ? current.expression : current.object)
  }
  return current?.type === 'Identifier' ? current : null
}

/**
 * Whether `variable` holds props, state or context: a parameter of a component or hook, a value from a hook call
 * other than `useRef`/`useId` (useState, useReducer, useContext, use, useMemo, useCallback, custom hooks), or an alias
 * that reads one of these without computing anything (`const v = value`, `const { a } = props`, `const n = list.length`),
 * followed through any number of aliases. State setters are excluded: they are stable functions, not data.
 */
function isPropsStateOrContext(sourceCode, variable, seen = new Set()) {
  const def = variable.defs[0]
  if (!def || seen.has(variable)) {
    return false
  }
  seen.add(variable)
  if (def.type === 'Parameter') {
    return FUNCTION_TYPES.has(def.node.type) && isComponentOrHook(def.node)
  }
  if (def.type !== 'Variable' || def.node.type !== 'VariableDeclarator') {
    return false
  }
  let init = def.node.init
  while (init && (init.type === 'AwaitExpression' || TS_EXPRESSIONS.has(init.type))) {
    init = init.type === 'AwaitExpression' ? init.argument : init.expression
  }
  const hook = init?.type === 'CallExpression' ? calleeName(init) : null
  if (hook !== null) {
    return isHookName(hook) && !REF_LIKE_HOOKS.has(hook) && !isStateSetter(variable)
  }
  const root = readRoot(init)
  const aliased = root && resolve(sourceCode, root)
  return aliased ? isPropsStateOrContext(sourceCode, aliased, seen) : false
}

const noStateCopyInit = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Reports an initial value of useState/useReducer (the argument of useState; the second and third arguments of ' +
        'useReducer; lazy initializer functions included) that reads a variable declared in the function making the ' +
        'call, i.e. the component or hook: its parameters (props), state, context, other hook results or any other ' +
        'local; and one that calls a hook itself (`useState(useContext(Ctx))`, `useState(useThing().value)`). ' +
        'Variables declared inside the initial value itself, literals, module-level constants and functions, imports ' +
        'and globals are allowed, so state never starts as a copy of data held elsewhere. Calls outside a function ' +
        'are not checked.',
    },
    messages: {
      copy: '{{hook}} must not start from "{{name}}" of the component: state is held once, not copied from props, state, context or hook results. Use a literal or module constant, or derive the value during render.',
      hookCall:
        '{{hook}} must not start from the result of {{name}}(): state is held once, not copied from props, state, context or hook results. Use a literal or module constant, or derive the value during render.',
    },
    schema: [],
  },
  create(context) {
    const sourceCode = context.sourceCode
    return {
      CallExpression(node) {
        const hook = calleeName(node)
        if (!STATE_HOOKS.has(hook ?? '')) {
          return
        }
        const fn = enclosingFunction(node)
        if (!fn) {
          return
        }
        const initialValues = hook === 'useState' ? [node.arguments[0]] : [node.arguments[1], node.arguments[2]]
        for (const initial of initialValues) {
          if (!initial) {
            continue
          }
          for (const identifier of valueIdentifiers(sourceCode, initial)) {
            const declared = resolve(sourceCode, identifier)?.identifiers[0]
            if (declared && isWithin(declared, fn) && !isWithin(declared, initial)) {
              context.report({ node: identifier, messageId: 'copy', data: { hook, name: identifier.name } })
            }
          }
          for (const call of hookCalls(sourceCode, initial)) {
            context.report({ node: call, messageId: 'hookCall', data: { hook, name: sourceCode.getText(call.callee) } })
          }
        }
      },
    }
  },
}

/** Methods that call their callback before they return: those of arrays, and `forEach` of `Map` and `Set`. */
const SYNC_CALLBACK_METHODS = new Set([
  'every',
  'filter',
  'find',
  'findIndex',
  'findLast',
  'findLastIndex',
  'flatMap',
  'forEach',
  'map',
  'reduce',
  'reduceRight',
  'some',
  'sort',
  'toSorted',
])

/**
 * Whether `fn` runs before the code around it goes on: called on the spot (`(() => …)()`), the callback of a
 * synchronous array method (`list.forEach(fn)`, see SYNC_CALLBACK_METHODS), the map function of `Array.from(list, fn)`
 * or the executor of `new Promise(fn)`. An async function never does: it counts as an asynchronous callback.
 */
function runsInline(fn) {
  const parent = fn.parent
  if (fn.async || !parent) {
    return false
  }
  if (parent.type === 'CallExpression' && parent.callee === fn) {
    return true
  }
  if (parent.type === 'NewExpression') {
    return parent.arguments[0] === fn && parent.callee.type === 'Identifier' && parent.callee.name === 'Promise'
  }
  if (parent.type !== 'CallExpression' || parent.callee.type !== 'MemberExpression') {
    return false
  }
  const method = calleeName(parent) ?? ''
  return (SYNC_CALLBACK_METHODS.has(method) && parent.arguments[0] === fn) || (method === 'from' && parent.arguments[1] === fn)
}

/** Whether `node` is the first argument of useEffect, useLayoutEffect or useInsertionEffect, i.e. the effect. */
function isEffectCallback(node) {
  const call = node.parent
  return call?.type === 'CallExpression' && call.arguments[0] === node && EFFECT_HOOKS.has(calleeName(call) ?? '')
}

/** The identifiers that read a named function (`function f() {}`, `const f = () => …`); none for other functions. */
function readsOfFunction(sourceCode, fn) {
  let declaration = null
  let name = null
  if (fn.type === 'FunctionDeclaration' && fn.id) {
    declaration = fn
    name = fn.id.name
  } else if (fn.parent?.type === 'VariableDeclarator' && fn.parent.init === fn && fn.parent.id.type === 'Identifier') {
    declaration = fn.parent
    name = fn.parent.id.name
  }
  if (!declaration) {
    return []
  }
  const variable = sourceCode.getDeclaredVariables(declaration).find((candidate) => candidate.name === name)
  return (variable?.references ?? []).filter((reference) => reference.isRead()).map((reference) => reference.identifier)
}

/**
 * Whether the code at `node` runs synchronously while an effect runs: in the effect callback itself, in a function
 * that runs inline there (see `runsInline`), or in a named function that is passed as the effect callback or called on
 * the spot from code that does. Promise callbacks, listeners, timers, async functions and the cleanup do not.
 */
function runsSynchronouslyInEffect(sourceCode, node, seen) {
  let fn = enclosingFunction(node)
  while (fn && runsInline(fn)) {
    fn = enclosingFunction(fn)
  }
  if (!fn || seen.has(fn)) {
    return false
  }
  seen.add(fn)
  if (isEffectCallback(fn)) {
    return true
  }
  return readsOfFunction(sourceCode, fn).some(
    (identifier) =>
      isEffectCallback(identifier) ||
      (identifier.parent?.type === 'CallExpression' &&
        identifier.parent.callee === identifier &&
        runsSynchronouslyInEffect(sourceCode, identifier.parent, seen)),
  )
}

const noSyncStateEffect = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Reports a call of a useState/useReducer setter (the second element of `const [value, setValue] = useState(…)`) ' +
        'that runs synchronously while a useEffect, useLayoutEffect or useInsertionEffect callback runs: the "derive ' +
        'state in an effect" pattern. Synchronous means in the effect callback itself; in a function called on the ' +
        'spot (`(() => …)()`), a callback of a synchronous array method (`forEach`, `map`, `filter`, `reduce`, …), the ' +
        'map function of `Array.from` or a `new Promise` executor there; or in a function of the component that is ' +
        'passed to the effect hook by name or called from such code. Calls in asynchronous callbacks the effect starts ' +
        '(promise callbacks, async functions, event listeners, timers, stream handlers) and in the cleanup are allowed.',
    },
    messages: {
      syncSet:
        '"{{name}}" is called directly in an effect: derive the value during render instead, or set it from an asynchronous callback the effect starts.',
    },
    schema: [],
  },
  create(context) {
    const sourceCode = context.sourceCode
    return {
      CallExpression(node) {
        if (node.callee.type !== 'Identifier') {
          return
        }
        const variable = resolve(sourceCode, node.callee)
        if (!variable || !isStateSetter(variable)) {
          return
        }
        if (runsSynchronouslyInEffect(sourceCode, node, new Set())) {
          context.report({ node, messageId: 'syncSet', data: { name: node.callee.name } })
        }
      },
    }
  },
}

const noRefMirror = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Reports an assignment `x.current = …` whose right-hand side reads props, state or context: a parameter of a ' +
        'component (PascalCase) or hook (`use…`), a variable taken from a hook call other than useRef/useId ' +
        '(useState and useReducer values, useContext, use, useMemo, useCallback, custom hooks), or a local alias that ' +
        'reads one of these without computing anything (`const v = value`, `const { a } = props`). Such a ref is a ' +
        'second, unrendered copy that goes stale. Values computed locally, refs, setters and literals are not ' +
        'reported, and neither is the initial value of useRef (a snapshot taken once, not kept in sync).',
    },
    messages: {
      mirror: '"{{name}}" is copied into a ref: props, state and context are read where they are held, not mirrored.',
    },
    schema: [],
  },
  create(context) {
    const sourceCode = context.sourceCode
    return {
      AssignmentExpression(node) {
        const target = node.left
        if (target.type !== 'MemberExpression' || target.computed || target.property.type !== 'Identifier' || target.property.name !== 'current') {
          return
        }
        for (const identifier of valueIdentifiers(sourceCode, node.right)) {
          const variable = resolve(sourceCode, identifier)
          if (variable && !isWithin(variable.identifiers[0] ?? identifier, node.right) && isPropsStateOrContext(sourceCode, variable)) {
            context.report({ node: identifier, messageId: 'mirror', data: { name: identifier.name } })
          }
        }
      },
    }
  },
}

/** Whether `variable` was declared as `const x = useNavigate()`. */
function isNavigateFunction(variable) {
  const def = variable?.defs[0]
  const init = def?.type === 'Variable' && def.node.type === 'VariableDeclarator' ? def.node.init : null
  return init?.type === 'CallExpression' && calleeName(init) === 'useNavigate'
}

function propertyName(property) {
  if (property.type !== 'Property' || property.computed) {
    return null
  }
  return property.key.type === 'Identifier' ? property.key.name : property.key.type === 'Literal' ? property.key.value : null
}

/**
 * The `state` property an options object passes on: written in the object literal, in an object spread into it, or in
 * the object literal a variable holds (`const options = { state }`, followed through any number of variables);
 * `null` when there is none.
 */
function routerStateProperty(sourceCode, node, seen = new Set()) {
  const value = unwrapTs(node)
  if (value?.type === 'Identifier') {
    const variable = resolve(sourceCode, value)
    const def = variable?.defs[0]
    if (!variable || seen.has(variable) || def?.type !== 'Variable' || def.node.type !== 'VariableDeclarator' || def.node.id.type !== 'Identifier') {
      return null
    }
    seen.add(variable)
    return routerStateProperty(sourceCode, def.node.init, seen)
  }
  if (value?.type !== 'ObjectExpression') {
    return null
  }
  for (const property of value.properties) {
    const found = property.type === 'SpreadElement' ? routerStateProperty(sourceCode, property.argument, seen) : null
    if (found) {
      return found
    }
    if (propertyName(property) === 'state') {
      return property
    }
  }
  return null
}

const noRouterState = {
  meta: {
    type: 'problem',
    docs: {
      description:
        'Reports router state: a `state` property in the options (second argument) of a call to `navigate`, ' +
        '`<object>.navigate` or a function from `useNavigate()`, and a `state` attribute on `<Link>`, `<NavLink>` or ' +
        '`<Navigate>`, also when it comes in a spread (`{ ...options }`, `<Link {...props}>`) or from a variable that ' +
        'holds the object literal (`const options = { state }`). History state is a hidden copy of app state that ' +
        'survives reloads and goes stale.',
    },
    messages: {
      routerState: 'Do not pass app state through the router ({{where}}): keep it in its provider, or put an identifier in the URL.',
    },
    schema: [],
  },
  create(context) {
    const sourceCode = context.sourceCode
    /** Reports `property` where it is written inside `node`, otherwise `node`, which brings it in. */
    const report = (node, property, where) => {
      context.report({ node: isWithin(property, node) ? property : node, messageId: 'routerState', data: { where } })
    }
    return {
      CallExpression(node) {
        const name = calleeName(node)
        const isNavigate =
          name === 'navigate' || (node.callee.type === 'Identifier' && isNavigateFunction(resolve(sourceCode, node.callee)))
        const options = node.arguments[1]
        const property = isNavigate && options ? routerStateProperty(sourceCode, options) : null
        if (property) {
          report(options, property, `${sourceCode.getText(node.callee)}(…, { state })`)
        }
      },
      JSXOpeningElement(node) {
        const element = node.name.type === 'JSXMemberExpression' ? node.name.property : node.name
        if (element.type !== 'JSXIdentifier' || !ROUTER_LINKS.has(element.name)) {
          return
        }
        for (const attribute of node.attributes) {
          if (attribute.type === 'JSXAttribute' && attribute.name.type === 'JSXIdentifier' && attribute.name.name === 'state') {
            report(attribute, attribute, `<${element.name} state>`)
          } else if (attribute.type === 'JSXSpreadAttribute') {
            const property = routerStateProperty(sourceCode, attribute.argument)
            if (property) {
              report(attribute, property, `<${element.name} {...{ state }}>`)
            }
          }
        }
      },
    }
  },
}

/** Whether `callee` is a name `createContext` was imported as: `import { createContext as create } from '…'`. */
function isCreateContextImport(sourceCode, callee) {
  if (callee.type !== 'Identifier') {
    return false
  }
  const def = resolve(sourceCode, callee)?.defs[0]
  if (def?.type !== 'ImportBinding' || def.node.type !== 'ImportSpecifier') {
    return false
  }
  const imported = def.node.imported
  return (imported.type === 'Identifier' ? imported.name : imported.value) === 'createContext'
}

const contextFilesOnly = {
  meta: {
    type: 'suggestion',
    docs: {
      description:
        'Reports a call of `createContext` or `React.createContext`, also under another name it was imported as ' +
        '(`import { createContext as create }`), in a file whose name does not end in `Context.ts`. ' +
        'Context objects live in their own `*Context.ts` file next to their provider, which keeps provider modules ' +
        'component-only (react/only-export-components) and makes every context easy to find.',
    },
    messages: {
      place: 'Create contexts only in a *Context.ts file.',
    },
    schema: [],
  },
  create(context) {
    const fileName = context.filename.split(/[\\/]/).pop() ?? ''
    if (fileName.endsWith('Context.ts')) {
      return {}
    }
    return {
      CallExpression(node) {
        if (calleeName(node) === 'createContext' || isCreateContextImport(context.sourceCode, node.callee)) {
          context.report({ node, messageId: 'place' })
        }
      },
    }
  },
}

export default {
  meta: { name: 'aicepeak-state' },
  rules: {
    'no-state-copy-init': noStateCopyInit,
    'no-sync-state-effect': noSyncStateEffect,
    'no-ref-mirror': noRefMirror,
    'no-router-state': noRouterState,
    'context-files-only': contextFilesOnly,
  },
}
