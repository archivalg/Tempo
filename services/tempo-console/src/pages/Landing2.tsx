import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { landing } from '../content/landingContent'
import './Landing2.css'

const price = {
  starter: { monthly: 9, annual: 7 },
  growth: { monthly: 15, annual: 12 },
}

function Mark() {
  return (
    <span className="l2-mark" aria-hidden="true">
      <i /><i /><i /><i /><i /><i /><i /><i /><i />
    </span>
  )
}

function ctaHref(plan = 'growth', billing = 'annual') {
  return `/signup?plan=${plan}&billing=${billing}`
}

function track(name: string, detail: Record<string, string | number>) {
  window.dispatchEvent(new CustomEvent('tempo-marketing-event', { detail: { name, ...detail, variant: 'landing2' } }))
}

export default function Landing2Page() {
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual')
  const [faqOpen, setFaqOpen] = useState(0)
  const [menu, setMenu] = useState(false)

  useEffect(() => {
    document.title = 'Tempo - AI Labour Command Centre for Warehousing and 3PL'
    const description = 'Tempo turns WMS demand, attendance and roster rules into an explainable labour plan for warehouses and 3PL operators.'
    const setMeta = (selector: string, attr: string, value: string) => {
      let el = document.head.querySelector(selector) as HTMLMetaElement | null
      if (!el) {
        el = document.createElement('meta')
        const name = selector.match(/\[(name|property)="([^"]+)"\]/)
        if (name) el.setAttribute(name[1], name[2])
        document.head.appendChild(el)
      }
      el.setAttribute(attr, value)
    }
    setMeta('meta[name="description"]', 'content', description)
    setMeta('meta[property="og:title"]', 'content', 'Tempo - Labour command for every warehouse shift')
    setMeta('meta[property="og:description"]', 'content', description)
  }, [])

  const chooseBilling = (next: 'monthly' | 'annual') => {
    setBilling(next)
    track('billing_toggle', { billing: next })
  }

  return (
    <div className="l2">
      <header className="l2-header">
        <nav className="l2-nav" aria-label="Marketing">
          <Link to="/landing2" className="l2-brand"><Mark /> <span>Tempo</span></Link>
          <button className="l2-menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>Menu</button>
          <div className={`l2-links${menu ? ' open' : ''}`}>
            <a href="#command" onClick={() => setMenu(false)}>Command centre</a>
            <a href="#models" onClick={() => setMenu(false)}>Models</a>
            <a href="#kiosk" onClick={() => setMenu(false)}>Kiosk</a>
            <a href="#pricing" onClick={() => setMenu(false)}>Pricing</a>
            <Link to="/">Sign in</Link>
            <a className="l2-btn primary" href={ctaHref()} onClick={() => track('cta_click', { location: 'nav', label: landing.nav.cta })}>{landing.nav.cta}</a>
          </div>
        </nav>
      </header>

      <main>
        <section className="l2-hero">
          <FlowingBackdrop />
          <div className="l2-container l2-hero-grid">
            <div className="l2-hero-copy">
              <p className="l2-kicker">AI labour command for warehousing and 3PL</p>
              <h1>Every shift, costed, covered and ready to publish.</h1>
              <p className="l2-lead">{landing.hero.lead}</p>
              <div className="l2-actions">
                <a className="l2-btn primary" href={ctaHref()} onClick={() => track('cta_click', { location: 'hero', label: landing.hero.primaryCta })}>{landing.hero.primaryCta}</a>
                <a className="l2-btn ghost" href="#command">Watch the shift resolve</a>
              </div>
              <div className="l2-proof" aria-label="Illustrative performance metrics">
                {landing.stats.items.slice(0, 3).map(([value, label]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}
              </div>
              <p className="l2-note">{landing.stats.note}</p>
            </div>
            <LabourOptimisationScene />
          </div>
        </section>

        <section id="command" className="l2-band">
          <div className="l2-container l2-command-section">
            <div>
              <p className="l2-kicker">One operating loop</p>
              <h2>Tempo sees the work, builds the roster, explains the move and follows the outcome.</h2>
            </div>
            <div className="l2-flow">
              {landing.how.steps.map(([n, color, title, body]) => (
                <article key={n}>
                  <span className={`l2-signal ${color}`} />
                  <code>{n}</code>
                  <h3>{title}</h3>
                  <p>{body}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="models" className="l2-section l2-container l2-models">
          <div className="l2-section-head">
            <p className="l2-kicker">{landing.engine.eyebrow}</p>
            <h2>{landing.engine.h2}</h2>
            <p>{landing.engine.lead}</p>
          </div>
          <div className="l2-model-board">
            {landing.engine.models.map(([n, tag, title, body]) => (
              <article key={n}>
                <div><code>{n}</code><span>{tag}</span></div>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="l2-section l2-container l2-evidence">
          <div className="l2-evidence-panel">
            <div>
              <p className="l2-kicker">{landing.explain.eyebrow}</p>
              <h2>{landing.explain.h2}</h2>
              <p>{landing.explain.lead}</p>
            </div>
            <div className="l2-evidence-card">
              <div className="l2-card-top"><span>Recommendation</span><strong>Move 2 pickers to Day</strong></div>
              {landing.explain.drivers.map((driver, index) => <p key={driver}><b>{String(index + 1).padStart(2, '0')}</b>{driver}</p>)}
              <div className="l2-gap"><span>Missing evidence</span><strong>{landing.explain.missing}</strong></div>
            </div>
          </div>
        </section>

        <section id="kiosk" className="l2-section l2-container l2-kiosk-section">
          <KioskStage />
          <div>
            <p className="l2-kicker">{landing.kiosk.eyebrow}</p>
            <h2>{landing.kiosk.h2}</h2>
            <p>{landing.kiosk.lead}</p>
            <div className="l2-feature-strip">
              {landing.kiosk.features.map(([title, body]) => <div key={title}><strong>{title}</strong><span>{body}</span></div>)}
            </div>
          </div>
        </section>

        <section className="l2-section l2-container">
          <div className="l2-split-head">
            <div>
              <p className="l2-kicker">{landing.integrations.eyebrow}</p>
              <h2>{landing.integrations.h2}</h2>
            </div>
            <p>{landing.integrations.lead}</p>
          </div>
          <div className="l2-integration-grid">
            {landing.integrations.items.map(([title, body]) => <article key={title}><h3>{title}</h3><p>{body}</p></article>)}
          </div>
        </section>

        <section id="pricing" className="l2-section l2-container l2-pricing">
          <div className="l2-section-head centre">
            <p className="l2-kicker">Pricing</p>
            <h2>Priced per worker. Built for measurable labour savings.</h2>
          </div>
          <div className="l2-toggle" role="group" aria-label="Billing period">
            <button aria-pressed={billing === 'monthly'} onClick={() => chooseBilling('monthly')}>Monthly</button>
            <button aria-pressed={billing === 'annual'} onClick={() => chooseBilling('annual')}>Annual - save 20%</button>
          </div>
          <div className="l2-price-grid">
            {landing.pricing.plans.map(([id, name, desc, features, cta, featured, badge]) => (
              <article key={id} className={featured ? 'featured' : ''}>
                <div className="l2-card-top"><h3>{name}</h3>{badge && <span>{badge}</span>}</div>
                {id === 'enterprise' ? <div className="l2-price">Custom</div> : <div className="l2-price">A${price[id as 'starter' | 'growth'][billing]}<small> / worker / month</small></div>}
                <p>{desc}</p>
                <ul>{features.map((f) => <li key={f}>{f}</li>)}</ul>
                <a className={`l2-btn ${featured ? 'green' : 'primary'}`} href={id === 'enterprise' ? '/contact' : ctaHref(id, billing)} onClick={() => track('cta_click', { location: `pricing_${id}`, label: cta })}>{cta}</a>
              </article>
            ))}
          </div>
        </section>

        <section className="l2-section l2-container l2-faq">
          <div>
            <p className="l2-kicker">FAQ</p>
            <h2>Practical details.</h2>
          </div>
          <div className="l2-accordion">
            {landing.faq.map(([q, a], index) => (
              <div key={q}>
                <button aria-expanded={faqOpen === index} aria-controls={`l2-faq-${index}`} onClick={() => { setFaqOpen(faqOpen === index ? -1 : index); track('faq_open', { index }) }}>
                  <span>{q}</span><b>{faqOpen === index ? '-' : '+'}</b>
                </button>
                <p id={`l2-faq-${index}`} hidden={faqOpen !== index}>{a}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="l2-section l2-container">
          <div className="l2-final">
            <p className="l2-kicker">Start with one site</p>
            <h2>Bring the roster. Tempo will show where the labour plan can move.</h2>
            <div className="l2-actions">
              <a className="l2-btn primary" href={ctaHref()} onClick={() => track('cta_click', { location: 'final', label: 'Start your free trial' })}>Start your free trial</a>
              <a className="l2-btn ghost light" href="/contact">Talk to sales</a>
            </div>
          </div>
        </section>
      </main>

      <footer className="l2-footer">
        <div className="l2-container l2-footer-grid">
          <div><Link to="/landing2" className="l2-brand"><Mark /> <span>Tempo</span></Link><p>AI labour optimisation for warehousing and 3PL.</p></div>
          {landing.footer.columns.map(([title, items]) => <div key={title}><h3>{title}</h3>{items.map((item) => <a href="#" key={item}>{item}</a>)}</div>)}
        </div>
        <div className="l2-container l2-legal"><span>2026 Tempo by Ensemble Solutions.</span><span><a href="#">Privacy</a> · <a href="#">Terms</a> · <a href="#">Security</a></span></div>
      </footer>
    </div>
  )
}

function FlowingBackdrop() {
  return (
    <div className="l2-flowing-bg" aria-hidden="true">
      <svg viewBox="0 0 1600 900" preserveAspectRatio="none">
        <defs>
          <linearGradient id="l2-wave-a" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="#57d88f" stopOpacity="0" />
            <stop offset="34%" stopColor="#57d88f" stopOpacity=".62" />
            <stop offset="62%" stopColor="#8168ff" stopOpacity=".54" />
            <stop offset="100%" stopColor="#3dc8d6" stopOpacity="0" />
          </linearGradient>
          <linearGradient id="l2-wave-b" x1="0%" x2="100%" y1="0%" y2="0%">
            <stop offset="0%" stopColor="#8168ff" stopOpacity="0" />
            <stop offset="44%" stopColor="#8168ff" stopOpacity=".5" />
            <stop offset="74%" stopColor="#57d88f" stopOpacity=".42" />
            <stop offset="100%" stopColor="#57d88f" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path className="wave main" d="M-90 642 C 178 520 340 790 590 640 S 1004 482 1264 628 S 1546 710 1690 568" />
        <path className="wave secondary" d="M-80 706 C 210 604 390 842 646 704 S 1034 550 1296 708 S 1540 778 1680 652" />
        <path className="wave tertiary" d="M-100 780 C 170 690 360 874 598 770 S 1008 664 1280 792 S 1510 850 1700 748" />
      </svg>
      <div className="l2-flow-dots">
        {Array.from({ length: 7 }).map((_, index) => <i key={index} />)}
      </div>
    </div>
  )
}

function LabourOptimisationScene() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const sceneRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const scene = sceneRef.current
    if (!canvas || !scene) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let frame = 0
    let raf = 0
    let width = 0
    let height = 0
    const pointer = { x: 0, y: 0, tx: 0, ty: 0 }

    const workers = Array.from({ length: 54 }, (_, index) => {
      const lane = index % 6
      const column = Math.floor(index / 6)
      return {
        sx: 70 + Math.random() * 520,
        sy: 56 + Math.random() * 420,
        tx: 112 + column * 50,
        ty: 108 + lane * 48,
        lane,
        delay: Math.random() * .34,
        conflict: index % 13 === 0 || index % 17 === 0,
      }
    })

    const resize = () => {
      const box = canvas.getBoundingClientRect()
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      width = Math.max(320, box.width)
      height = Math.max(360, box.height)
      canvas.width = Math.round(width * dpr)
      canvas.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const onPointerMove = (event: PointerEvent) => {
      const rect = scene.getBoundingClientRect()
      pointer.tx = ((event.clientX - rect.left) / rect.width - .5) * 22
      pointer.ty = ((event.clientY - rect.top) / rect.height - .5) * 18
    }

    const mix = (a: number, b: number, t: number) => a + (b - a) * t
    const ease = (t: number) => 1 - Math.pow(1 - Math.max(0, Math.min(1, t)), 3)

    const draw = () => {
      frame += reduceMotion ? 0 : 1
      pointer.x = mix(pointer.x, pointer.tx, .055)
      pointer.y = mix(pointer.y, pointer.ty, .055)
      ctx.clearRect(0, 0, width, height)

      const time = reduceMotion ? 140 : frame
      const resolve = reduceMotion ? 1 : (Math.sin(time / 120) + 1) / 2
      const resolveEase = ease(resolve)

      const gradient = ctx.createRadialGradient(width * .52, height * .46, 20, width * .52, height * .5, width * .72)
      gradient.addColorStop(0, 'rgba(87,216,143,.22)')
      gradient.addColorStop(.42, 'rgba(61,200,214,.10)')
      gradient.addColorStop(1, 'rgba(87,216,143,0)')
      ctx.fillStyle = gradient
      ctx.fillRect(0, 0, width, height)

      ctx.save()
      ctx.translate(pointer.x, pointer.y)

      for (let i = 0; i < 7; i += 1) {
        const y = 92 + i * 48
        ctx.beginPath()
        ctx.strokeStyle = i === 0 || i === 6 ? 'rgba(87,216,143,.14)' : 'rgba(255,255,255,.075)'
        ctx.lineWidth = 1
        ctx.moveTo(70, y)
        ctx.bezierCurveTo(width * .34, y - 26, width * .56, y + 20, width - 58, y - 6)
        ctx.stroke()
      }

      workers.forEach((worker, index) => {
        const localT = ease(resolveEase - worker.delay)
        const wave = Math.sin(time / 24 + index * .72) * (1 - localT) * 14
        const x = mix(worker.sx, worker.tx, localT) + pointer.x * .18
        const y = mix(worker.sy, worker.ty, localT) + wave + pointer.y * .12
        const isConflict = worker.conflict && resolveEase < .72
        const alpha = .42 + localT * .5

        ctx.beginPath()
        ctx.fillStyle = isConflict ? `rgba(236,96,82,${alpha})` : `rgba(87,216,143,${alpha})`
        ctx.shadowColor = isConflict ? 'rgba(236,96,82,.42)' : 'rgba(87,216,143,.5)'
        ctx.shadowBlur = isConflict ? 18 : 13
        ctx.arc(x, y, isConflict ? 5 : 4.2, 0, Math.PI * 2)
        ctx.fill()
        ctx.shadowBlur = 0
      })

      for (let lane = 0; lane < 6; lane += 1) {
        const x = 92 + lane * 78
        const h = 46 + lane * 7
        const y = 416 - h
        ctx.fillStyle = `rgba(87,216,143,${.08 + resolveEase * .16})`
        ctx.strokeStyle = `rgba(87,216,143,${.18 + resolveEase * .2})`
        ctx.lineWidth = 1
        ctx.beginPath()
        ctx.roundRect(x, y, 54, h, 8)
        ctx.fill()
        ctx.stroke()
      }

      ctx.restore()
      raf = requestAnimationFrame(draw)
    }

    resize()
    scene.addEventListener('pointermove', onPointerMove)
    window.addEventListener('resize', resize)
    draw()

    return () => {
      cancelAnimationFrame(raf)
      scene.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('resize', resize)
    }
  }, [])

  return (
    <div className="l2-scene" ref={sceneRef} aria-label="Animated labour optimisation scene">
      <canvas ref={canvasRef} className="l2-scene-canvas" aria-hidden="true" />
      <div className="l2-scene-glow" aria-hidden="true" />
      <div className="l2-scene-panel roster">
        <div className="l2-card-top"><span>Roster pattern</span><strong>Balanced</strong></div>
        <div className="l2-scene-rows">
          {['Early', 'Day', 'Late'].map((label, row) => (
            <div key={label}>
              <b>{label}</b>
              {Array.from({ length: 8 }).map((_, index) => <i key={`${label}-${index}`} className={(row + index) % 7 === 0 ? 'resolved' : 'ok'} />)}
            </div>
          ))}
        </div>
      </div>
      <div className="l2-scene-panel outcome">
        <code>CONFLICTS RESOLVED</code>
        <strong>18 workers moved into coverage</strong>
        <p>Illustrative shift pattern after Tempo optimisation.</p>
      </div>
      <div className="l2-scene-panel cost">
        <span>Labour delta</span>
        <strong>-11.0%</strong>
        <small>modelled pilot scenario</small>
      </div>
      <div className="l2-scene-panel approve">
        <span>Recommendation</span>
        <strong>Ready for approval</strong>
        <button>Approve & publish</button>
      </div>
    </div>
  )
}

function KioskStage() {
  return (
    <aside className="l2-kiosk-stage" aria-label="Tempo kiosk and attendance preview">
      <div className="l2-device">
        <code>KIOSK - DOCK 3 - 06:58</code>
        <h3>Enter your PIN</h3>
        <div className="l2-pin"><i /><i /><i /><i /></div>
        <div className="l2-pad">{['1','2','3','4','5','6','7','8','9','Clear','0','Back'].map((key) => <button key={key}>{key}</button>)}</div>
        <div className="l2-confirm"><strong>Clocked in - Priya S.</strong><span>Rostered shift matched</span></div>
      </div>
      <div className="l2-supervisor">
        <span>Supervisor queue</span>
        <p><b>Late</b> 2 workers</p>
        <p><b>Unrostered</b> 1 clock-in</p>
        <p><b>Coverage</b> 98.6%</p>
      </div>
    </aside>
  )
}
