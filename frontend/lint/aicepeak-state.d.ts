// Types of the oxlint JS plugin in aicepeak-state.js, so its test is type-checked (tsconfig.lint.json).
import type { RuleTester } from 'oxlint/plugins-dev'

/** An oxlint JS rule, as `RuleTester.run` takes it. */
type Rule = Parameters<RuleTester['run']>[1]

/** Every rule of the plugin says in `meta.docs.description` exactly what it reports. */
type DocumentedRule = Rule & { meta: { docs: { description: string } } }

export type RuleName = 'no-state-copy-init' | 'no-sync-state-effect' | 'no-ref-mirror' | 'no-router-state' | 'context-files-only'

declare const plugin: {
  meta: { name: 'aicepeak-state' }
  rules: Record<RuleName, DocumentedRule>
}

export default plugin
