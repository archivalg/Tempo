import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { TempoContextProvider, useTempoContext } from './TempoContextProvider'

const SAMPLE = {
  tenant_id: 'ten_test',
  site_ids: ['site_mel_01'],
  customer_ids: [],
  user_id: 'usr_test',
  roles: ['operations_manager'],
  purpose: 'labour.console',
  correlation_id: 'cor_test',
}

function Probe() {
  const { context, setContext, clearContext } = useTempoContext()
  return (
    <div>
      <span data-testid="tenant">{context?.tenant_id ?? 'none'}</span>
      <button onClick={() => setContext(SAMPLE)}>set</button>
      <button onClick={clearContext}>clear</button>
    </div>
  )
}

describe('TempoContextProvider', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts with no context when localStorage is empty', () => {
    render(
      <TempoContextProvider>
        <Probe />
      </TempoContextProvider>,
    )
    expect(screen.getByTestId('tenant').textContent).toBe('none')
  })

  it('persists a set context to localStorage and restores it on remount', () => {
    const { unmount } = render(
      <TempoContextProvider>
        <Probe />
      </TempoContextProvider>,
    )
    fireEvent.click(screen.getByText('set'))
    expect(screen.getByTestId('tenant').textContent).toBe('ten_test')
    unmount()

    render(
      <TempoContextProvider>
        <Probe />
      </TempoContextProvider>,
    )
    expect(screen.getByTestId('tenant').textContent).toBe('ten_test')
  })

  it('clearContext removes it from localStorage', () => {
    render(
      <TempoContextProvider>
        <Probe />
      </TempoContextProvider>,
    )
    fireEvent.click(screen.getByText('set'))
    fireEvent.click(screen.getByText('clear'))
    expect(screen.getByTestId('tenant').textContent).toBe('none')
    expect(localStorage.getItem('tempo-console.context')).toBeNull()
  })
})
