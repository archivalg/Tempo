import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { landing } from '../content/landingContent'
import './Landing.css'

const price = {
  starter: { monthly: 9, annual: 7 },
  growth: { monthly: 15, annual: 12 },
}

function Mark({ large = false }: { large?: boolean }) {
  return (
    <span className={`lp-mark${large ? ' large' : ''}`} aria-hidden="true">
      <i /><i /><i /><i /><i /><i /><i /><i /><i />
    </span>
  )
}

function ctaHref(plan = 'growth', billing = 'annual') {
  return `/signup?plan=${plan}&billing=${billing}`
}

function track(name: string, detail: Record<string, string | number>) {
  window.dispatchEvent(new CustomEvent('tempo-marketing-event', { detail: { name, ...detail } }))
}

export default function LandingPage() {
  const [billing, setBilling] = useState<'monthly' | 'annual'>('annual')
  const [faqOpen, setFaqOpen] = useState(0)
  const [menu, setMenu] = useState(false)

  useEffect(() => {
    document.title = 'Tempo — AI Labour Optimisation & Rostering for Warehouses and 3PL'
    const description = 'Tempo is the AI-native labour platform for warehousing and 3PL. Forecast demand, build optimised rosters, run kiosk clock-in and publish with one approval. Start a free 14-day trial.'
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
    setMeta('meta[property="og:title"]', 'content', 'Tempo — Every shift, perfectly in tempo')
    setMeta('meta[property="og:description"]', 'content', 'AI rostering, time & attendance and labour cost optimisation for warehouses and 3PL operators.')
  }, [])

  const chooseBilling = (next: 'monthly' | 'annual') => {
    setBilling(next)
    track('billing_toggle', { billing: next })
  }

  return (
    <div className="lp">
      <header className="lp-header">
        <nav className="lp-nav" aria-label="Marketing">
          <Link to="/landing" className="lp-brand"><Mark /> <span>Tempo</span></Link>
          <button className="lp-menu" aria-expanded={menu} onClick={() => setMenu(!menu)}>Menu</button>
          <div className={`lp-links${menu ? ' open' : ''}`}>
            {landing.nav.links.map(([label, href]) => <a key={href} href={href} onClick={() => setMenu(false)}>{label}</a>)}
            <Link to="/" className="lp-signin">{landing.nav.signIn}</Link>
            <a className="lp-pill dark" href={ctaHref()} onClick={() => track('cta_click', { location: 'nav', label: landing.nav.cta })}>{landing.nav.cta}</a>
          </div>
        </nav>
      </header>

      <main>
        <section className="lp-hero lp-container">
          <div className="lp-hero-copy">
            <div className="lp-eyebrow"><span />{landing.hero.eyebrow}</div>
            <h1>{landing.hero.h1}</h1>
            <p className="lp-lead">{landing.hero.lead}</p>
            <div className="lp-cta-row">
              <a className="lp-pill dark" href={ctaHref()} onClick={() => track('cta_click', { location: 'hero', label: landing.hero.primaryCta })}>{landing.hero.primaryCta}</a>
              <a className="lp-pill light" href="#how">{landing.hero.secondaryCta}</a>
            </div>
            <p className="lp-trust">{landing.hero.trust.join(' · ')}</p>
          </div>
          <ProductMock />
        </section>

        <section className="lp-stats" aria-label="Illustrative results">
          <div className="lp-container lp-stat-grid">
            {landing.stats.items.map(([value, label]) => <div key={label}><strong>{value}</strong><span>{label}</span></div>)}
          </div>
          <p className="lp-note lp-container">{landing.stats.note}</p>
        </section>

        <section id="how" className="lp-section lp-container">
          <div className="lp-section-head">
            <div className="lp-eyebrow"><span />{landing.how.eyebrow}</div>
            <h2>{landing.how.h2}</h2>
            <p>{landing.how.lead}</p>
          </div>
          <ol className="lp-steps">
            {landing.how.steps.map(([n, color, title, body]) => (
              <li key={n}>
                <span className="lp-step-n">{n}</span>
                <i className={`lp-dot ${color}`} aria-hidden="true" />
                <h3>{title}</h3>
                <p>{body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section id="engine" className="lp-section lp-engine lp-container">
          <div className="lp-sticky">
            <div className="lp-eyebrow"><span />{landing.engine.eyebrow}</div>
            <h2>{landing.engine.h2}</h2>
            <p>{landing.engine.lead}</p>
            <a className="lp-textlink" href={ctaHref('growth', billing)} onClick={() => track('cta_click', { location: 'engine', label: landing.engine.link })}>{landing.engine.link}</a>
          </div>
          <div className="lp-model-grid">
            {landing.engine.models.map(([n, tag, title, body]) => (
              <article key={n}>
                <div><span>{n}</span><code>{tag}</code></div>
                <h3>{title}</h3>
                <p>{body}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="lp-section lp-container">
          <div className="lp-dark-panel">
            <div>
              <div className="lp-eyebrow"><span />{landing.explain.eyebrow}</div>
              <h2>{landing.explain.h2}</h2>
              <p>{landing.explain.lead}</p>
              <ul className="lp-bullets">
                {landing.explain.bullets.map(([color, text]) => <li key={text}><i className={`lp-dot ${color}`} aria-hidden="true" />{text}</li>)}
              </ul>
            </div>
            <div className="lp-why-card">
              <div className="lp-row"><strong>Why this roster</strong><span className="lp-status warn">confidence 0.91 · high</span></div>
              <h3>Primary drivers</h3>
              {landing.explain.drivers.map((d) => <p key={d}>{d}</p>)}
              <div className="lp-missing"><strong>Missing evidence</strong><span>{landing.explain.missing}</span></div>
              <div className="lp-status-row"><span className="lp-status warn">validated</span><span className="lp-status ok">approved</span><span className="lp-status ok">confirmed</span></div>
            </div>
          </div>
        </section>

        <section className="lp-section lp-kiosk lp-container">
          <KioskMock />
          <div>
            <div className="lp-eyebrow"><span />{landing.kiosk.eyebrow}</div>
            <h2>{landing.kiosk.h2}</h2>
            <p>{landing.kiosk.lead}</p>
            <div className="lp-feature-list">
              {landing.kiosk.features.map(([title, body]) => <div key={title}><strong>{title}</strong><span>{body}</span></div>)}
            </div>
          </div>
        </section>

        <section id="integrations" className="lp-section lp-container">
          <div className="lp-split-head">
            <div><div className="lp-eyebrow"><span />{landing.integrations.eyebrow}</div><h2>{landing.integrations.h2}</h2></div>
            <p>{landing.integrations.lead}</p>
          </div>
          <div className="lp-tile-grid">
            {landing.integrations.items.map(([title, body]) => <article key={title}><h3>{title}</h3><p>{body}</p></article>)}
          </div>
        </section>

        <section className="lp-section lp-security lp-container">
          <div><div className="lp-eyebrow"><span />{landing.security.eyebrow}</div><h2>{landing.security.h2}</h2><p>{landing.security.lead}</p></div>
          <div className="lp-security-grid">{landing.security.items.map(([title, body]) => <article key={title}><h3>{title}</h3><p>{body}</p></article>)}</div>
        </section>

        <section id="pricing" className="lp-section lp-pricing lp-container">
          <div className="lp-centre"><div className="lp-eyebrow"><span />PRICING</div><h2>Priced per worker. Pays for itself.</h2></div>
          <div className="lp-toggle" role="group" aria-label="Billing period">
            <button aria-pressed={billing === 'monthly'} onClick={() => chooseBilling('monthly')}>Monthly</button>
            <button aria-pressed={billing === 'annual'} onClick={() => chooseBilling('annual')}>Annual · save 20%</button>
          </div>
          <div className="lp-price-grid">
            {landing.pricing.plans.map(([id, name, desc, features, cta, featured, badge]) => (
              <article key={id} className={featured ? 'featured' : ''}>
                <div className="lp-row"><h3>{name}</h3>{badge && <span className="lp-popular">{badge}</span>}</div>
                {id === 'enterprise' ? <div className="lp-price">Custom</div> : <div className="lp-price">A${price[id as 'starter' | 'growth'][billing]}<span> per worker / month</span></div>}
                <p>{desc}</p>
                <ul>{features.map((f) => <li key={f}>✓ {f}</li>)}</ul>
                <a className={`lp-pill ${featured ? 'green' : 'dark'}`} href={id === 'enterprise' ? '/contact' : ctaHref(id, billing)} onClick={() => track('cta_click', { location: `pricing_${id}`, label: cta })}>{cta}</a>
              </article>
            ))}
          </div>
        </section>

        <section className="lp-section lp-faq lp-container">
          <div><div className="lp-eyebrow"><span />FAQ</div><h2>Questions, answered.</h2></div>
          <div className="lp-accordion">
            {landing.faq.map(([q, a], i) => (
              <div key={q}>
                <button aria-expanded={faqOpen === i} aria-controls={`faq-${i}`} onClick={() => { setFaqOpen(faqOpen === i ? -1 : i); track('faq_open', { index: i }) }}>
                  <span>{q}</span><b>{faqOpen === i ? '−' : '+'}</b>
                </button>
                <p id={`faq-${i}`} hidden={faqOpen !== i}>{a}</p>
              </div>
            ))}
          </div>
        </section>

        <section id="resources" className="lp-section lp-container">
          <div className="lp-row lp-resource-head"><h2>From the Tempo journal</h2><a className="lp-textlink" href="/journal">All resources →</a></div>
          <div className="lp-resource-grid">
            {landing.resources.map(([tag, title], index) => <article key={title}><div className={`lp-cover cover-${index + 1}`}><span /><span /><span /></div><code>{tag}</code><h3>{title}</h3></article>)}
          </div>
        </section>

        <section className="lp-section lp-container">
          <div className="lp-final">
            <Mark large />
            <h2>Get every site to green.</h2>
            <p>Start a 14-day free trial on one site. Bring your roster and we'll show you the savings in week one.</p>
            <div className="lp-cta-row"><a className="lp-pill dark" href={ctaHref()} onClick={() => track('cta_click', { location: 'final', label: 'Start your free trial' })}>Start your free trial</a><a className="lp-pill light" href="/contact">Talk to sales</a></div>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-container lp-footer-grid">
          <div><Link to="/landing" className="lp-brand"><Mark /> <span>Tempo</span></Link><p>AI labour optimisation for warehousing and 3PL.</p></div>
          {landing.footer.columns.map(([title, items]) => <div key={title}><h3>{title}</h3>{items.map((item) => <a href="#" key={item}>{item}</a>)}</div>)}
        </div>
        <div className="lp-container lp-legal"><span>© 2026 Tempo by Ensemble Solutions. Made in Melbourne.</span><span><a href="#">Privacy</a> · <a href="#">Terms</a> · <a href="#">Security</a></span></div>
      </footer>
    </div>
  )
}

function ProductMock() {
  const { mock } = landing.hero
  return (
    <aside className="lp-product-card" aria-label="Product roster approval mock">
      <div className="lp-mock-toolbar">
        <div>
          <code>{mock.label}</code>
          <h2>{mock.title}</h2>
        </div>
        <span className="lp-status ok">Completed</span>
      </div>

      <div className="lp-mock-layout">
        <div className="lp-mock-main">
          <div className="lp-chart-card">
            <div className="lp-row">
              <strong>Coverage forecast</strong>
              <span className="lp-status warn">2 tight shifts</span>
            </div>
            <svg viewBox="0 0 420 144" role="img" aria-label="Coverage forecast chart">
              <path className="grid" d="M0 32H420M0 72H420M0 112H420" />
              <path className="area" d="M0 112C48 86 76 76 118 80C168 85 190 38 236 44C282 50 300 92 346 76C380 64 394 46 420 38V144H0Z" />
              <path className="line" d="M0 112C48 86 76 76 118 80C168 85 190 38 236 44C282 50 300 92 346 76C380 64 394 46 420 38" />
            </svg>
            <div className="lp-chart-axis"><span>Mon</span><span>Wed</span><span>Fri</span><span>Sun</span></div>
          </div>

          <div className="lp-heat">
            <span />
            {mock.heatmap.days.map((d) => <b key={d}>{d}</b>)}
            {mock.heatmap.rows.map(([name, cells]) => (
              <div key={name} className="lp-heat-row">
                <strong>{name}</strong>
                {[...cells].map((c, i) => <i key={`${name}-${i}`} className={c} title={mock.heatmap.legend[c as 'g' | 'a' | 'r']} />)}
              </div>
            ))}
          </div>
        </div>

        <div className="lp-mock-side">
          <div className="lp-score">
            <span>Optimisation score</span>
            <strong>91</strong>
            <small>High confidence</small>
          </div>
          <div className="lp-driver-list">
            <strong>Drivers</strong>
            <p>Inbound demand +18%</p>
            <p>Agency hours −140h</p>
            <p>Forklift expiry x2</p>
          </div>
        </div>
      </div>

      <div className="lp-cost-strip"><div><span>Baseline</span><b>{mock.baseline}</b></div><div><span>Proposed</span><b>{mock.proposed}</b></div><div><span>Delta</span><b>{mock.delta}</b></div></div>
      <div className="lp-row"><span>{mock.confidence}</span><button>{mock.action}</button></div>
    </aside>
  )
}

function KioskMock() {
  return (
    <aside className="lp-kiosk-card" aria-label="Kiosk mock">
      <code>KIOSK · DOCK 3 · 06:58</code>
      <h3>Enter your PIN</h3>
      <div className="lp-pins"><i /><i /><i /><i /></div>
      <div className="lp-keypad">{['1','2','3','4','5','6','7','8','9','Clear','0','⌫'].map((k) => <button key={k}>{k}</button>)}</div>
      <div className="lp-confirm">Clocked in · Priya S.<span>Rostered shift matched</span></div>
    </aside>
  )
}
