import { useContext } from 'react'
import {
  ProjectFlowActionsContext,
  ProjectFlowStateContext,
  type ProjectFlowActions,
  type ProjectFlowState,
} from './projectFlowContext.ts'

/** The flow's state, held by the nearest `ProjectFlowProvider`; derive what to show with `selectors.ts`. */
export function useProjectFlowState(): ProjectFlowState {
  const value = useContext(ProjectFlowStateContext)
  if (!value) {
    throw new Error('useProjectFlowState must be used inside <ProjectFlowProvider>')
  }
  return value
}

/** The flow's actions: `addFiles`, `removeDocument` and `advance`. */
export function useProjectFlowActions(): ProjectFlowActions {
  const value = useContext(ProjectFlowActionsContext)
  if (!value) {
    throw new Error('useProjectFlowActions must be used inside <ProjectFlowProvider>')
  }
  return value
}
