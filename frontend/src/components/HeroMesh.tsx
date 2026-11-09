import { useReducedMotion } from 'framer-motion'
import { useEffect, useRef } from 'react'
import { cssVarRgb } from '../lib/color'

interface Particle {
  x: number
  y: number
  r: number
  vx: number
  vy: number
  alpha: number
}

const COUNT = 14

/** Slow gradient mesh in teal and sand with a few soft drifting marigold particles. */
export function HeroMesh() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const reduce = useReducedMotion()

  useEffect(() => {
    const canvas = canvasRef.current
    const context = canvas?.getContext('2d')
    if (!canvas || !context) return
    let frame = 0
    let width = 0
    let height = 0
    const ratio = Math.min(window.devicePixelRatio || 1, 2)
    const [red, green, blue] = cssVarRgb('--marigold')

    const resize = () => {
      width = canvas.clientWidth
      height = canvas.clientHeight
      canvas.width = width * ratio
      canvas.height = height * ratio
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
    }
    resize()

    const particles: Particle[] = Array.from({ length: COUNT }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      r: 3 + Math.random() * 9,
      vx: (Math.random() - 0.5) * 0.18,
      vy: -0.05 - Math.random() * 0.15,
      alpha: 0.15 + Math.random() * 0.35,
    }))

    const draw = () => {
      context.clearRect(0, 0, width, height)
      for (const p of particles) {
        const gradient = context.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 2.4)
        gradient.addColorStop(0, `rgba(${red}, ${green}, ${blue}, ${p.alpha})`)
        gradient.addColorStop(1, `rgba(${red}, ${green}, ${blue}, 0)`)
        context.fillStyle = gradient
        context.beginPath()
        context.arc(p.x, p.y, p.r * 2.4, 0, Math.PI * 2)
        context.fill()
      }
    }

    const step = () => {
      for (const p of particles) {
        p.x += p.vx
        p.y += p.vy
        if (p.y < -30) {
          p.y = height + 30
          p.x = Math.random() * width
        }
        if (p.x < -30) p.x = width + 30
        if (p.x > width + 30) p.x = -30
      }
      draw()
      frame = window.requestAnimationFrame(step)
    }

    if (reduce) draw()
    else frame = window.requestAnimationFrame(step)
    window.addEventListener('resize', resize)
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('resize', resize)
    }
  }, [reduce])

  return (
    <div className="mesh pointer-events-none absolute inset-0 -z-10 overflow-hidden" aria-hidden>
      <canvas ref={canvasRef} className="size-full" />
    </div>
  )
}
