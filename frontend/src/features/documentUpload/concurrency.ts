/** Runs tasks one after another, in the order they were given. */
export type SerialQueue = {
  /** True while no task waits or runs. */
  readonly idle: boolean
  /** Runs `task` after every task given before has settled; settles like it. */
  run<T>(task: () => Promise<T>): Promise<T>
}

/**
 * A queue for requests that must not overlap. A task's own handlers (`run(task).then(…)`) run after the queue has
 * counted it as finished, so they already see `idle` as it is without that task.
 */
export function createSerialQueue(): SerialQueue {
  let tail: Promise<unknown> = Promise.resolve()
  let pending = 0
  return {
    get idle() {
      return pending === 0
    },
    run<T>(task: () => Promise<T>): Promise<T> {
      pending++
      const result = tail.then(task).finally(() => {
        pending--
      })
      tail = result.catch(() => undefined)
      return result
    },
  }
}

/** Runs at most a given number of tasks at the same time. */
export type TaskLimiter = {
  /** Starts `task` once fewer than the limit run, in the order given; settles like it. */
  run<T>(task: () => Promise<T>): Promise<T>
}

export function createTaskLimiter(limit: number): TaskLimiter {
  let active = 0
  const waiting: Array<() => void> = []

  function startNext() {
    while (active < limit && waiting.length > 0) {
      active++
      waiting.shift()?.()
    }
  }

  return {
    run<T>(task: () => Promise<T>): Promise<T> {
      return new Promise<T>((resolve, reject) => {
        waiting.push(() => {
          Promise.resolve()
            .then(task)
            .then(resolve, reject)
            .finally(() => {
              active--
              startNext()
            })
        })
        startNext()
      })
    },
  }
}
