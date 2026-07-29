import { useEffect, useRef } from 'react'

// 纯装饰动画：一个缓慢自转的发光体，不连接任何后端数据。
export default function MemoryLifeform({ dark }) {
  const ref = useRef(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    let raf
    let W = 0, H = 0, dpr = Math.min(window.devicePixelRatio || 1, 2)

    // 颜色随背景明暗切换：深色底用浅色画、浅色底用深色画
    const C = dark
      ? { line: 'rgba(255,255,255,0.10)', glow: 'rgba(255,255,255,1)', dot: '#ffffff', node: 'rgba(255,255,255,0.18)', ring: 'rgba(255,255,255,0.30)', dash: 'rgba(255,255,255,0.16)' }
      : { line: 'rgba(17,17,17,0.07)', glow: 'rgba(17,17,17,1)', dot: '#111111', node: 'rgba(17,17,17,0.14)', ring: 'rgba(17,17,17,0.22)', dash: 'rgba(17,17,17,0.12)' }

    const resize = () => {
      const wrap = canvas.parentElement
      W = wrap.clientWidth
      H = wrap.clientHeight
      canvas.width = W * dpr
      canvas.height = H * dpr
      canvas.style.width = W + 'px'
      canvas.style.height = H + 'px'
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(canvas.parentElement)

    // 固定的装饰轨道（与数据无关）
    const N = 6
    const orbit = Array.from({ length: N }, (_, i) => ({
      r: 52 + i * 13,
      a: (i / N) * Math.PI * 2,
      sp: 0.12 + (i % 3) * 0.04,
      dir: i % 2 === 0 ? 1 : -1,
      sz: 2.4 + (i % 3)
    }))

    let t = 0
    const draw = () => {
      t += 0.016
      const cx = W / 2, cy = H / 2
      ctx.clearRect(0, 0, W, H)

      // 按画布实际尺寸自适应：最外圈留出边距，绝不溢出边框
      const reach = 52 + (N - 1) * 13 + 6
      const scale = Math.max(0.45, Math.min(1.25, (Math.min(W, H) / 2 - 14) / reach))

      // 中心核：单层柔和光晕 + 实心点（不叠加多层朦胧）
      const cg = ctx.createRadialGradient(cx, cy, 1, cx, cy, 24)
      cg.addColorStop(0, C.glow)
      cg.addColorStop(1, 'rgba(0,0,0,0)')
      ctx.globalAlpha = 0.5
      ctx.fillStyle = cg
      ctx.beginPath(); ctx.arc(cx, cy, 24, 0, Math.PI * 2); ctx.fill()
      ctx.globalAlpha = 1
      ctx.fillStyle = C.dot
      ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2); ctx.fill()

      // 轨道节点：中心到节点的细射线 + 干净实心点（无圆环线）
      for (const o of orbit) {
        const ang = o.a + t * o.sp * o.dir
        const x = cx + Math.cos(ang) * o.r * scale
        const y = cy + Math.sin(ang) * o.r * scale
        ctx.strokeStyle = C.node
        ctx.lineWidth = 1
        ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke()
        ctx.fillStyle = C.dot
        ctx.beginPath(); ctx.arc(x, y, o.sz, 0, Math.PI * 2); ctx.fill()
      }

      raf = requestAnimationFrame(draw)
    }
    draw()

    return () => { cancelAnimationFrame(raf); ro.disconnect() }
  }, [dark])

  return <canvas ref={ref} className="lm-orb-canvas" />
}
