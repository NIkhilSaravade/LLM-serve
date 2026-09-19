import {
  Activity, BookOpen, Cpu, FlaskConical, Gauge, Layers, Network, Play, Scale, ShieldCheck, Terminal, TrendingUp, TriangleAlert,
  Route, Wrench, type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  id: string
  label: string
  icon: LucideIcon
}
export interface NavGroup {
  title: string
  items: NavItem[]
}

export const NAV: NavGroup[] = [
  {
    title: 'The result',
    items: [
      { id: 'overview', label: 'Overview', icon: BookOpen },
      { id: 'results', label: 'Ablation', icon: Gauge },
      { id: 'load', label: 'Under load', icon: TrendingUp },
    ],
  },
  {
    title: 'How it is built',
    items: [
      { id: 'journey', label: 'Build order', icon: Route },
      { id: 'architecture', label: 'System design', icon: Network },
      { id: 'memory', label: 'KV memory', icon: Layers },
      { id: 'motion', label: 'In motion', icon: Play },
      { id: 'cpu', label: 'CPU limits', icon: Cpu },
    ],
  },
  {
    title: 'Proof',
    items: [
      { id: 'correctness', label: 'Correctness', icon: ShieldCheck },
      { id: 'operations', label: 'Operations', icon: Activity },
    ],
  },
  {
    title: 'Honesty',
    items: [
      { id: 'problems', label: 'Problems fixed', icon: Wrench },
      { id: 'negative-results', label: 'Negative results', icon: TriangleAlert },
      { id: 'methodology', label: 'Method', icon: FlaskConical },
      { id: 'limitations', label: 'Limitations', icon: Scale },
      { id: 'reproduce', label: 'Reproduce', icon: Terminal },
    ],
  },
]

export const SECTION_IDS: readonly string[] = NAV.flatMap((g) => g.items.map((i) => i.id))
