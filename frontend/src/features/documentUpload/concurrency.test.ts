import { describe, expect, it } from 'vitest'
import { deferred } from '../../test/deferred.ts'
import { createSerialQueue, createTaskLimiter } from './concurrency.ts'

describe('createSerialQueue', () => {
  it('starts each task only after the previous one settled, failed ones included', async () => {
    const queue = createSerialQueue()
    const first = deferred<string>()
    const second = deferred<string>()
    const started: string[] = []

    const a = queue.run(() => {
      started.push('a')
      return first.promise
    })
    const b = queue.run(() => {
      started.push('b')
      return second.promise
    })
    await Promise.resolve()
    expect(started).toEqual(['a'])
    expect(queue.idle).toBe(false)

    first.reject(new Error('a failed'))
    await expect(a).rejects.toThrow('a failed')
    await expect.poll(() => started).toEqual(['a', 'b'])
    second.resolve('b done')
    await expect(b).resolves.toBe('b done')
    expect(queue.idle).toBe(true)
  })

  it('counts a task as finished before its own handlers run', async () => {
    const queue = createSerialQueue()

    const idleInHandler = await queue.run(async () => 'x').then(() => queue.idle)

    expect(idleInHandler).toBe(true)
  })
})

describe('createTaskLimiter', () => {
  it('runs at most the limit at the same time, in order', async () => {
    const limiter = createTaskLimiter(2)
    const gates = [deferred<void>(), deferred<void>(), deferred<void>()]
    let running = 0
    let most = 0
    const started: number[] = []

    const all = gates.map((gate, index) =>
      limiter.run(async () => {
        started.push(index)
        running++
        most = Math.max(most, running)
        await gate.promise
        running--
      }),
    )
    await expect.poll(() => started).toEqual([0, 1])
    gates[1]?.resolve()
    await expect.poll(() => started).toEqual([0, 1, 2])
    gates[0]?.resolve()
    gates[2]?.resolve()
    await Promise.all(all)

    expect(most).toBe(2)
  })
})
