<script setup lang="ts">
import { gsap } from 'gsap'
import { onBeforeUnmount, onMounted, ref } from 'vue'

type KnowledgeGroup = 'core' | 'identity' | 'security'

interface KnowledgeStarMapHandle {
  setFocus: (group: KnowledgeGroup, active: boolean) => void
  capture: () => void
  restore: () => void
}

interface Point3D {
  x: number
  y: number
  z: number
}

interface ProjectedPoint extends Point3D {
  scale: number
  depth: number
}

interface KnowledgeNode extends Point3D {
  label?: string
  group: KnowledgeGroup
  core?: boolean
  major?: boolean
}

interface KnowledgeEdge {
  from: number
  to: number
  group: KnowledgeGroup
}

const canvasRef = ref<HTMLCanvasElement | null>(null)
const datumRef = ref<HTMLDivElement | null>(null)

const TAU = Math.PI * 2
const scene = {
  yaw: -0.34,
  pitch: 0.08,
  pointerX: 0,
  pointerY: 0,
  intro: 0,
  focus: 0,
  focusGroup: 'core' as KnowledgeGroup,
  pulse: 0,
  pulseIndex: 0,
  coreGlow: 0.25,
  collapse: 0,
}

const nodes: KnowledgeNode[] = [
  { x: 0, y: 0, z: 0, label: 'ORIGIN', group: 'core', core: true },
  {
    x: -0.68,
    y: -0.17,
    z: 0.16,
    label: 'SOURCE',
    group: 'identity',
    major: true,
  },
  { x: -0.42, y: 0.43, z: -0.31, group: 'identity' },
  {
    x: 0.34,
    y: -0.49,
    z: 0.28,
    label: 'MEMORY',
    group: 'identity',
    major: true,
  },
  { x: -0.73, y: 0.18, z: 0.36, group: 'identity' },
  {
    x: 0.65,
    y: 0.15,
    z: -0.18,
    label: 'ACCESS',
    group: 'security',
    major: true,
  },
  { x: 0.29, y: 0.58, z: 0.17, group: 'security' },
  { x: 0.72, y: -0.28, z: 0.08, group: 'security' },
  {
    x: -0.06,
    y: -0.7,
    z: -0.15,
    label: 'INFERENCE',
    group: 'core',
    major: true,
  },
  { x: -0.24, y: 0.7, z: 0.04, group: 'core' },
  { x: 0.03, y: -0.24, z: -0.7, group: 'identity' },
  { x: 0.47, y: 0.42, z: -0.47, group: 'security' },
  { x: -0.48, y: -0.53, z: -0.25, group: 'core' },
  { x: -0.12, y: 0.28, z: 0.69, group: 'identity' },
  { x: 0.18, y: -0.05, z: 0.78, group: 'security' },
  { x: 0.56, y: -0.5, z: -0.28, group: 'core' },
]

const edges: KnowledgeEdge[] = [
  { from: 0, to: 1, group: 'identity' },
  { from: 0, to: 3, group: 'identity' },
  { from: 0, to: 5, group: 'security' },
  { from: 0, to: 8, group: 'core' },
  { from: 1, to: 2, group: 'identity' },
  { from: 1, to: 4, group: 'identity' },
  { from: 2, to: 13, group: 'identity' },
  { from: 3, to: 10, group: 'identity' },
  { from: 3, to: 12, group: 'core' },
  { from: 5, to: 6, group: 'security' },
  { from: 5, to: 7, group: 'security' },
  { from: 6, to: 11, group: 'security' },
  { from: 7, to: 14, group: 'security' },
  { from: 8, to: 9, group: 'core' },
  { from: 8, to: 12, group: 'core' },
  { from: 9, to: 13, group: 'identity' },
  { from: 11, to: 15, group: 'security' },
]

const distantStars = Array.from({ length: 24 }, (_item, index) => {
  const y = 1 - (2 * (index + 0.5)) / 24
  const radial = Math.sqrt(1 - y * y)
  const angle = index * 2.3999632297
  return {
    x: Math.cos(angle) * radial * 1.08,
    y: y * 1.08,
    z: Math.sin(angle) * radial * 1.08,
    size: index % 7 === 0 ? 1.35 : 0.72,
  }
})

const ringDefinitions = [
  { radius: 0.98, rx: 1.02, ry: 0.05, rz: 0.18, alpha: 0.085, dash: [] },
  { radius: 0.79, rx: 0.12, ry: 1.13, rz: -0.24, alpha: 0.07, dash: [] },
  {
    radius: 0.62,
    rx: 0.43,
    ry: -0.68,
    rz: 0.48,
    alpha: 0.052,
    dash: [2, 6],
  },
]

const viewport = { width: 0, height: 0, dpr: 1, mobile: false }
let drawing: CanvasRenderingContext2D | null = null
let mediaContext: ReturnType<typeof gsap.matchMedia> | null = null
let sceneAnimations: Array<{ kill: () => void }> = []
let tickerActive = false
let resizeFrame = 0
let reducedMotion = false
let pointerXTo: ReturnType<typeof gsap.quickTo> | null = null
let pointerYTo: ReturnType<typeof gsap.quickTo> | null = null

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function rotateLocal(
  point: Point3D,
  rotationX: number,
  rotationY: number,
  rotationZ: number,
): Point3D {
  const cosX = Math.cos(rotationX)
  const sinX = Math.sin(rotationX)
  const y1 = point.y * cosX - point.z * sinX
  const z1 = point.y * sinX + point.z * cosX
  const cosY = Math.cos(rotationY)
  const sinY = Math.sin(rotationY)
  const x2 = point.x * cosY + z1 * sinY
  const z2 = -point.x * sinY + z1 * cosY
  const cosZ = Math.cos(rotationZ)
  const sinZ = Math.sin(rotationZ)

  return {
    x: x2 * cosZ - y1 * sinZ,
    y: x2 * sinZ + y1 * cosZ,
    z: z2,
  }
}

function transformPoint(point: Point3D): Point3D {
  const shrink = 1 - scene.collapse * 0.86
  return rotateLocal(
    { x: point.x * shrink, y: point.y * shrink, z: point.z * shrink },
    scene.pitch + scene.pointerY,
    scene.yaw + scene.pointerX,
    -0.055,
  )
}

function projectPoint(point: Point3D): ProjectedPoint {
  const rotated = transformPoint(point)
  const cameraDistance = 3.25
  const perspective = cameraDistance / (cameraDistance - rotated.z)
  const centerX = viewport.width * (viewport.mobile ? 0.5 : 0.43)
  const centerY = viewport.height * (viewport.mobile ? 0.23 : 0.5)
  const radius = viewport.mobile
    ? Math.min(viewport.width * 0.51, viewport.height * 0.29)
    : Math.min(viewport.width * 0.45, viewport.height * 0.42)
  const introScale = 0.92 + scene.intro * 0.08

  return {
    x: centerX + rotated.x * radius * perspective * introScale,
    y: centerY + rotated.y * radius * perspective * introScale,
    z: rotated.z,
    scale: perspective,
    depth: clamp((rotated.z + 1.1) / 2.2, 0, 1),
  }
}

function setCanvasSize(): void {
  const canvas = canvasRef.value
  if (!canvas || !drawing) return
  const bounds = canvas.getBoundingClientRect()
  viewport.width = Math.max(1, Math.round(bounds.width))
  viewport.height = Math.max(1, Math.round(bounds.height))
  viewport.dpr = Math.min(window.devicePixelRatio || 1, 2)
  viewport.mobile = window.innerWidth <= 760

  const pixelWidth = Math.round(viewport.width * viewport.dpr)
  const pixelHeight = Math.round(viewport.height * viewport.dpr)
  if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
    canvas.width = pixelWidth
    canvas.height = pixelHeight
  }
  drawing.setTransform(viewport.dpr, 0, 0, viewport.dpr, 0, 0)
}

function drawRings(globalAlpha: number): void {
  const context = drawing
  if (!context) return
  ringDefinitions.forEach((ring) => {
    const points: ProjectedPoint[] = []
    const resolution = 112

    for (let index = 0; index <= resolution; index += 1) {
      const angle = (index / resolution) * TAU
      const local = rotateLocal(
        {
          x: Math.cos(angle) * ring.radius,
          y: Math.sin(angle) * ring.radius,
          z: 0,
        },
        ring.rx,
        ring.ry,
        ring.rz,
      )
      points.push(projectPoint(local))
    }

    context.lineWidth = 0.7
    context.setLineDash(ring.dash)
    for (let index = 1; index < points.length; index += 1) {
      const from = points[index - 1]
      const to = points[index]
      if (!from || !to) continue
      const depth = (from.depth + to.depth) * 0.5
      context.beginPath()
      context.moveTo(from.x, from.y)
      context.lineTo(to.x, to.y)
      context.strokeStyle = `rgba(255,255,255,${ring.alpha * (0.28 + depth * 0.92) * globalAlpha})`
      context.stroke()
    }
  })
  context.setLineDash([])
}

function groupEmphasis(group: KnowledgeGroup): number {
  if (scene.focus < 0.01) return 1
  return group === scene.focusGroup ? 1 + scene.focus * 0.72 : 1 - scene.focus * 0.78
}

function drawDistantStars(globalAlpha: number): void {
  const context = drawing
  if (!context) return
  distantStars.forEach((star) => {
    const projected = projectPoint(star)
    const alpha = (0.08 + projected.depth * 0.19) * globalAlpha
    context.beginPath()
    context.arc(projected.x, projected.y, star.size * projected.scale, 0, TAU)
    context.fillStyle = `rgba(255,255,255,${alpha})`
    context.fill()
  })
}

function drawConnections(projectedNodes: ProjectedPoint[], globalAlpha: number): void {
  if (!drawing) return
  const orderedEdges = edges
    .map((edge) => ({
      ...edge,
      depth:
        ((projectedNodes[edge.from]?.depth ?? 0) +
          (projectedNodes[edge.to]?.depth ?? 0)) *
        0.5,
    }))
    .sort((first, second) => first.depth - second.depth)

  orderedEdges.forEach((edge) => {
    const from = projectedNodes[edge.from]
    const to = projectedNodes[edge.to]
    if (!from || !to) return
    const emphasis = groupEmphasis(edge.group)
    const alpha = (0.055 + edge.depth * 0.15) * emphasis * globalAlpha
    drawing?.beginPath()
    drawing?.moveTo(from.x, from.y)
    drawing?.lineTo(to.x, to.y)
    if (!drawing) return
    drawing.lineWidth =
      edge.group === scene.focusGroup && scene.focus > 0.1 ? 0.9 : 0.58
    drawing.strokeStyle = `rgba(255,255,255,${clamp(alpha, 0, 0.48)})`
    drawing.stroke()
  })
}

function drawPulse(projectedNodes: ProjectedPoint[], globalAlpha: number): void {
  if (!drawing || scene.pulse <= 0.005 || scene.collapse > 0.7) return
  const edge = edges[scene.pulseIndex % edges.length]
  if (!edge) return
  const from = projectedNodes[edge.from]
  const to = projectedNodes[edge.to]
  if (!from || !to) return
  const progress = scene.pulse
  const x = from.x + (to.x - from.x) * progress
  const y = from.y + (to.y - from.y) * progress
  const pulseAlpha = Math.sin(progress * Math.PI) * globalAlpha

  drawing.save()
  drawing.globalCompositeOperation = 'lighter'
  drawing.beginPath()
  drawing.moveTo(from.x, from.y)
  drawing.lineTo(x, y)
  drawing.lineWidth = 1
  drawing.strokeStyle = `rgba(255,255,255,${pulseAlpha * 0.34})`
  drawing.stroke()
  drawing.shadowColor = 'rgba(255,255,255,0.9)'
  drawing.shadowBlur = 14
  drawing.beginPath()
  drawing.arc(x, y, 1.35, 0, TAU)
  drawing.fillStyle = `rgba(255,255,255,${pulseAlpha * 0.95})`
  drawing.fill()
  drawing.restore()
}

function drawNode(
  node: KnowledgeNode,
  projected: ProjectedPoint,
  globalAlpha: number,
): void {
  if (!drawing) return
  const emphasis = groupEmphasis(node.group)
  const alpha = clamp((0.24 + projected.depth * 0.68) * emphasis * globalAlpha, 0, 1)
  const baseRadius = node.core ? 3.1 : node.major ? 2.05 : 1.05
  const radius =
    baseRadius * projected.scale * (node.core ? 1 + scene.collapse * 1.1 : 1)

  if (node.core) {
    drawing.save()
    drawing.shadowColor = 'rgba(255,255,255,0.84)'
    drawing.shadowBlur = 11 + scene.coreGlow * 12
    drawing.beginPath()
    drawing.arc(projected.x, projected.y, radius, 0, TAU)
    drawing.fillStyle = `rgba(255,255,255,${alpha})`
    drawing.fill()
    drawing.shadowBlur = 0
    drawing.beginPath()
    drawing.arc(
      projected.x,
      projected.y,
      9 + scene.coreGlow * 3.5 + scene.collapse * 5,
      0,
      TAU,
    )
    drawing.strokeStyle = `rgba(255,255,255,${0.12 + scene.coreGlow * 0.12})`
    drawing.lineWidth = 0.8
    drawing.stroke()
    drawing.restore()
    return
  }

  if (node.major) {
    drawing.beginPath()
    drawing.arc(projected.x, projected.y, radius + 4.8, 0, TAU)
    drawing.strokeStyle = `rgba(255,255,255,${alpha * 0.25})`
    drawing.lineWidth = 0.7
    drawing.stroke()
  }

  drawing.beginPath()
  drawing.arc(projected.x, projected.y, radius, 0, TAU)
  drawing.fillStyle = `rgba(255,255,255,${alpha})`
  drawing.fill()

  if (node.major && node.label && !viewport.mobile && scene.collapse < 0.22) {
    const labelAlpha = alpha * (1 - scene.collapse) * 0.58
    drawing.beginPath()
    drawing.moveTo(projected.x + radius + 4.8, projected.y)
    drawing.lineTo(projected.x + radius + 11, projected.y)
    drawing.strokeStyle = `rgba(255,255,255,${labelAlpha * 0.55})`
    drawing.lineWidth = 0.6
    drawing.stroke()
    drawing.font = '500 7px Consolas, "SFMono-Regular", monospace'
    drawing.textBaseline = 'middle'
    drawing.fillStyle = `rgba(255,255,255,${labelAlpha})`
    drawing.fillText(node.label, projected.x + radius + 14, projected.y + 0.3)
  }
}

function renderStarMap(): void {
  if (!drawing) return
  drawing.clearRect(0, 0, viewport.width, viewport.height)
  const globalAlpha = clamp(scene.intro * (1 - scene.collapse * 0.72), 0, 1)
  if (globalAlpha <= 0.001) return

  const projectedNodes = nodes.map(projectPoint)
  drawRings(globalAlpha)
  drawDistantStars(globalAlpha)
  drawConnections(projectedNodes, globalAlpha)
  drawPulse(projectedNodes, globalAlpha)

  nodes
    .map((node, index) => ({ node, projected: projectedNodes[index] }))
    .filter(
      (item): item is { node: KnowledgeNode; projected: ProjectedPoint } =>
        item.projected !== undefined,
    )
    .sort((first, second) => first.projected.z - second.projected.z)
    .forEach(({ node, projected }) => drawNode(node, projected, globalAlpha))
}

function registerAnimation<T extends { kill: () => void }>(animation: T): T {
  sceneAnimations.push(animation)
  return animation
}

function stopScene(): void {
  sceneAnimations.forEach((animation) => animation.kill())
  sceneAnimations = []
  gsap.killTweensOf(scene)
  if (canvasRef.value) gsap.killTweensOf(canvasRef.value)
  if (datumRef.value) gsap.killTweensOf(datumRef.value)
  if (tickerActive) {
    gsap.ticker.remove(renderStarMap)
    tickerActive = false
  }
}

function resetScene(): void {
  Object.assign(scene, {
    yaw: -0.34,
    pitch: 0.08,
    pointerX: 0,
    pointerY: 0,
    intro: 0,
    focus: 0,
    focusGroup: 'core',
    pulse: 0,
    pulseIndex: 0,
    coreGlow: 0.25,
    collapse: 0,
  })
}

function handlePointer(event: PointerEvent): void {
  pointerXTo?.((event.clientX / window.innerWidth - 0.5) * 0.16)
  pointerYTo?.((event.clientY / window.innerHeight - 0.5) * -0.12)
}

function resetPointer(): void {
  pointerXTo?.(0)
  pointerYTo?.(0)
}

function buildScene(): void {
  const canvas = canvasRef.value
  if (!canvas) return

  mediaContext = gsap.matchMedia()
  mediaContext.add(
    {
      desktop: '(min-width: 761px)',
      reduceMotion: '(prefers-reduced-motion: reduce)',
    },
    (context) => {
      stopScene()
      resetScene()
      setCanvasSize()
      const desktop = context.conditions?.desktop === true
      reducedMotion = context.conditions?.reduceMotion === true

      if (reducedMotion) {
        scene.intro = 1
        gsap.set(canvas, { autoAlpha: 0.72 })
        renderStarMap()
        return undefined
      }

      gsap.ticker.add(renderStarMap)
      tickerActive = true
      registerAnimation(
        gsap.to(canvas, {
          autoAlpha: desktop ? 0.92 : 0.72,
          duration: 1.45,
          ease: 'power3.out',
        }),
      )
      registerAnimation(
        gsap.to(scene, { intro: 1, duration: 1.75, ease: 'power3.out' }),
      )
      if (datumRef.value) {
        registerAnimation(
          gsap.from(datumRef.value, {
            y: 8,
            autoAlpha: 0,
            duration: 0.65,
            delay: 0.7,
            ease: 'power3.out',
          }),
        )
      }
      registerAnimation(
        gsap.to(scene, {
          yaw: `+=${TAU}`,
          duration: 190,
          ease: 'none',
          repeat: -1,
        }),
      )
      registerAnimation(
        gsap.to(scene, {
          pitch: 0.19,
          duration: 17,
          ease: 'sine.inOut',
          repeat: -1,
          yoyo: true,
        }),
      )
      registerAnimation(
        gsap.to(scene, {
          coreGlow: 1,
          duration: 3.8,
          ease: 'sine.inOut',
          repeat: -1,
          yoyo: true,
        }),
      )
      registerAnimation(
        gsap.fromTo(
          scene,
          { pulse: 0 },
          {
            pulse: 1,
            duration: 3.2,
            ease: 'power1.inOut',
            repeat: -1,
            repeatDelay: 7.8,
            onRepeat: () => {
              scene.pulseIndex = (scene.pulseIndex + 5) % edges.length
            },
          },
        ),
      )

      if (desktop) {
        pointerXTo = gsap.quickTo(scene, 'pointerX', {
          duration: 1.35,
          ease: 'power3.out',
        })
        pointerYTo = gsap.quickTo(scene, 'pointerY', {
          duration: 1.35,
          ease: 'power3.out',
        })
        window.addEventListener('pointermove', handlePointer, { passive: true })
        document.documentElement.addEventListener('pointerleave', resetPointer)
      }

      return () => {
        window.removeEventListener('pointermove', handlePointer)
        document.documentElement.removeEventListener('pointerleave', resetPointer)
        pointerXTo = null
        pointerYTo = null
        stopScene()
      }
    },
  )
}

function handleResize(): void {
  window.cancelAnimationFrame(resizeFrame)
  resizeFrame = window.requestAnimationFrame(() => {
    setCanvasSize()
    renderStarMap()
  })
}

function handleVisibilityChange(): void {
  if (reducedMotion) return
  if (document.hidden && tickerActive) {
    gsap.ticker.remove(renderStarMap)
    tickerActive = false
  } else if (!document.hidden && !tickerActive) {
    gsap.ticker.add(renderStarMap)
    tickerActive = true
  }
}

function setFocus(group: KnowledgeGroup, active: boolean): void {
  if (reducedMotion) return
  if (active) scene.focusGroup = group
  gsap.to(scene, {
    focus: active ? 1 : 0,
    duration: active ? 0.68 : 0.52,
    ease: 'power2.out',
    overwrite: 'auto',
  })
}

function capture(): void {
  if (reducedMotion) return
  gsap.killTweensOf(scene, 'collapse,focus')
  gsap.to(scene, {
    collapse: 1,
    focus: 0,
    duration: 0.76,
    ease: 'power3.inOut',
    overwrite: 'auto',
  })
}

function restore(): void {
  if (reducedMotion) return
  gsap.to(scene, {
    collapse: 0,
    duration: 0.92,
    ease: 'power3.out',
    overwrite: 'auto',
  })
}

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  drawing = canvas.getContext('2d', { alpha: true })
  if (!drawing) return
  setCanvasSize()
  buildScene()
  window.addEventListener('resize', handleResize, { passive: true })
  document.addEventListener('visibilitychange', handleVisibilityChange)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.cancelAnimationFrame(resizeFrame)
  stopScene()
  mediaContext?.revert()
  mediaContext = null
  drawing = null
})

defineExpose<KnowledgeStarMapHandle>({ setFocus, capture, restore })
</script>

<template>
  <div class="star-map" aria-hidden="true">
    <div class="star-map__halo"></div>
    <canvas ref="canvasRef" class="star-map__canvas"></canvas>
    <div class="star-map__reticle"></div>
    <div ref="datumRef" class="star-map__datum">
      <span>SEMANTIC FIELD</span>
      <i></i>
      <span>∞ / 07</span>
    </div>
  </div>
</template>

<style scoped>
.star-map {
  position: fixed;
  z-index: 1;
  inset: 0 34% 0 0;
  overflow: hidden;
  pointer-events: none;
  contain: strict;
}

.star-map::after {
  position: absolute;
  z-index: 2;
  top: 0;
  right: -1rem;
  bottom: 0;
  width: 2rem;
  background: #050505;
  box-shadow: -4rem 0 5rem 3rem #050505;
  content: '';
}

.star-map__halo {
  position: absolute;
  top: 50%;
  left: 43%;
  width: min(66vw, 58rem);
  aspect-ratio: 1;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.012);
  box-shadow: 0 0 8rem 5rem rgba(255, 255, 255, 0.02);
  filter: blur(2rem);
  transform: translate(-50%, -50%);
}

.star-map__canvas {
  position: absolute;
  inset: 0;
  display: block;
  width: 100%;
  height: 100%;
  opacity: 0;
  will-change: opacity;
}

.star-map__reticle {
  position: absolute;
  top: 50%;
  left: 43%;
  width: clamp(3.5rem, 5vw, 5.2rem);
  aspect-ratio: 1;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 50%;
  opacity: 0.7;
  transform: translate(-50%, -50%);
}

.star-map__reticle::before,
.star-map__reticle::after {
  position: absolute;
  top: 50%;
  left: 50%;
  background: rgba(255, 255, 255, 0.18);
  content: '';
  transform: translate(-50%, -50%);
}

.star-map__reticle::before {
  width: calc(100% + 2.3rem);
  height: 1px;
  border-right: 1.2rem solid rgba(255, 255, 255, 0.18);
  border-left: 1.2rem solid rgba(255, 255, 255, 0.18);
  background: transparent;
}

.star-map__reticle::after {
  width: 1px;
  height: calc(100% + 2.3rem);
  border-top: 1.2rem solid rgba(255, 255, 255, 0.18);
  border-bottom: 1.2rem solid rgba(255, 255, 255, 0.18);
  background: transparent;
}

.star-map__datum {
  position: absolute;
  bottom: clamp(2rem, 6vh, 4.8rem);
  left: clamp(2rem, 5vw, 5rem);
  display: flex;
  align-items: center;
  gap: 0.65rem;
  color: rgba(255, 255, 255, 0.23);
  font-family: Consolas, 'SFMono-Regular', monospace;
  font-size: 0.5rem;
  letter-spacing: 0.18em;
}

.star-map__datum i {
  width: 2.5rem;
  height: 1px;
  background: rgba(255, 255, 255, 0.12);
}

@media (max-width: 760px) {
  .star-map {
    inset: 0;
    opacity: 0.52;
  }

  .star-map::after {
    top: auto;
    right: 0;
    bottom: -1rem;
    left: 0;
    width: auto;
    height: 2rem;
    box-shadow: 0 -5rem 6rem 4rem #050505;
  }

  .star-map__halo,
  .star-map__reticle {
    top: 23%;
    left: 50%;
  }

  .star-map__halo {
    width: 110vw;
  }

  .star-map__datum {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .star-map__canvas {
    will-change: auto;
  }
}
</style>
