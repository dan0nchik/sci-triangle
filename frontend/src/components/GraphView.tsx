import { useEffect, useRef } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition, EventObject } from 'cytoscape'
import type { GraphEdge, GraphNode, NodeType, Subgraph } from '../api/types'
import { CHAIN_TYPES, NODE_COLORS } from '../lib/ontology'

function toElements(g: Subgraph): ElementDefinition[] {
  const present = new Set(g.nodes.map((n) => n.id))
  const nodes: ElementDefinition[] = g.nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.name.length > 26 ? n.name.slice(0, 24) + '…' : n.name,
      ntype: n.type,
      color: NODE_COLORS[n.type] ?? '#90a4ae',
    },
  }))
  const edges: ElementDefinition[] = g.edges
    .filter((e) => present.has(e.src) && present.has(e.dst))
    .map((e, i) => ({
      data: {
        id: e.id ?? `e${i}_${e.src}_${e.dst}`,
        source: e.src,
        target: e.dst,
        etype: e.type,
        contradicts: e.type === 'contradicts' ? 1 : 0,
        manual: e.created_by && e.created_by !== 'pipeline' ? 1 : 0,
      },
    }))
  return [...nodes, ...edges]
}

// Поиск ребра исходной модели по данным cytoscape-ребра.
function findEdge(g: Subgraph, source: string, target: string, etype: string): GraphEdge | null {
  return (
    g.edges.find((e) => e.src === source && e.dst === target && e.type === etype) ?? null
  )
}

const STYLE: cytoscape.StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      label: 'data(label)',
      color: '#e2e8f0',
      'font-size': 9,
      'text-valign': 'bottom',
      'text-halign': 'center',
      'text-margin-y': 3,
      width: 26,
      height: 26,
      'border-width': 1.5,
      'border-color': '#0b0f14',
      'text-wrap': 'wrap',
      'text-max-width': '90px',
    },
  },
  {
    selector: 'node[ntype = "Assertion"]',
    style: { shape: 'round-diamond', width: 30, height: 30 },
  },
  { selector: 'node[ntype = "Publication"]', style: { shape: 'round-rectangle' } },
  { selector: 'node[ntype = "Expert"]', style: { shape: 'star' } },
  { selector: 'node[ntype = "Condition"]', style: { shape: 'hexagon' } },
  {
    selector: 'edge',
    style: {
      width: 1.4,
      'line-color': '#37485a',
      'target-arrow-color': '#37485a',
      'target-arrow-shape': 'triangle',
      'arrow-scale': 0.7,
      'curve-style': 'bezier',
      opacity: 0.75,
    },
  },
  {
    selector: 'edge[contradicts = 1]',
    style: {
      'line-color': '#f43f5e',
      'target-arrow-color': '#f43f5e',
      'source-arrow-color': '#f43f5e',
      'source-arrow-shape': 'triangle',
      'line-style': 'dashed',
      width: 2.2,
      opacity: 1,
    },
  },
  {
    selector: 'edge[manual = 1]',
    style: { 'line-color': '#22d3ee', 'line-style': 'dotted', width: 2 },
  },
  {
    selector: '.dim',
    style: { opacity: 0.12 },
  },
  {
    selector: '.chain',
    style: { 'border-color': '#3ea6ff', 'border-width': 3, opacity: 1 },
  },
  {
    selector: 'edge.chain',
    style: { 'line-color': '#3ea6ff', 'target-arrow-color': '#3ea6ff', width: 2.6, opacity: 1 },
  },
  {
    selector: 'node:selected',
    style: { 'border-color': '#ffffff', 'border-width': 3 },
  },
]

export function GraphView({
  graph,
  onSelectNode,
  onSelectEdge,
  highlightChain = false,
  layoutName = 'cose',
  focusId = null,
}: {
  graph: Subgraph
  onSelectNode?: (n: GraphNode | null) => void
  onSelectEdge?: (e: GraphEdge | null) => void
  highlightChain?: boolean
  layoutName?: 'cose' | 'concentric' | 'breadthfirst'
  focusId?: string | null
}) {
  const ref = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)

  // Фокус на узле (поиск/навигация) без пересоздания графа.
  // focusId может нести force-маркер "id#timestamp" для повторного фокуса.
  useEffect(() => {
    const cy = cyRef.current
    if (!cy || !focusId) return
    const realId = focusId.split('#')[0]
    const n = cy.getElementById(realId)
    if (n && n.length) {
      cy.elements().removeClass('dim')
      cy.elements().not(n.closedNeighborhood()).addClass('dim')
      cy.animate({ center: { eles: n }, zoom: 1.3 }, { duration: 350 })
      onSelectNode?.(graph.nodes.find((x) => x.id === realId) ?? null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId])

  useEffect(() => {
    if (!ref.current) return
    const cy = cytoscape({
      container: ref.current,
      elements: toElements(graph),
      style: STYLE,
      layout: { name: layoutName, animate: false, padding: 30, ...(layoutName === 'cose' ? { nodeRepulsion: 8000, idealEdgeLength: 90 } : {}) } as cytoscape.LayoutOptions,
      minZoom: 0.2,
      maxZoom: 3,
      wheelSensitivity: 0.25,
    })
    cyRef.current = cy
    // E2E test hook: expose the cytoscape core so Playwright can tap a node/edge
    // without pixel-hunting on the canvas. Harmless in production.
    ;(window as unknown as { __cy?: Core }).__cy = cy

    const nodeById = new Map(graph.nodes.map((n) => [n.id, n]))

    cy.on('tap', 'node', (evt: EventObject) => {
      const id = evt.target.id() as string
      const node = nodeById.get(id) ?? null
      onSelectNode?.(node)
      onSelectEdge?.(null)
      // подсветка соседства
      cy.elements().removeClass('dim')
      const nb = evt.target.closedNeighborhood()
      cy.elements().not(nb).addClass('dim')
    })

    cy.on('tap', 'edge', (evt: EventObject) => {
      const e = evt.target
      const edge = findEdge(graph, e.data('source'), e.data('target'), e.data('etype'))
      onSelectEdge?.(edge)
      onSelectNode?.(null)
      cy.elements().removeClass('dim')
      cy.elements().not(e.connectedNodes().union(e)).addClass('dim')
    })

    cy.on('tap', (evt: EventObject) => {
      if (evt.target === cy) {
        cy.elements().removeClass('dim')
        onSelectNode?.(null)
        onSelectEdge?.(null)
      }
    })

    // Подсветка цепочки материал → процесс → оборудование
    if (highlightChain) {
      const chainNodes = cy.nodes().filter((n) => CHAIN_TYPES.includes(n.data('ntype') as NodeType))
      chainNodes.addClass('chain')
      chainNodes.connectedEdges().forEach((e) => {
        const s = e.source().data('ntype') as NodeType
        const t = e.target().data('ntype') as NodeType
        if (CHAIN_TYPES.includes(s) && CHAIN_TYPES.includes(t)) e.addClass('chain')
      })
    }

    return () => {
      cy.destroy()
      cyRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, highlightChain, layoutName])

  return <div ref={ref} data-testid="graph-canvas" className="h-full w-full" />
}

// экспорт для «раскрыть соседей» из внешних компонентов
export function mergeSubgraphs(a: Subgraph, b: Subgraph): Subgraph {
  const nm = new Map<string, GraphNode>()
  for (const n of [...a.nodes, ...b.nodes]) nm.set(n.id, n)
  const es = new Map<string, GraphEdge>()
  for (const e of [...a.edges, ...b.edges]) es.set(`${e.src}|${e.type}|${e.dst}`, e)
  return { nodes: [...nm.values()], edges: [...es.values()] }
}
