import Sidebar from './components/Sidebar'
import Hero from './components/Hero'
import { Results, Load } from './components/Results'
import Journey from './components/Journey'
import SystemDiagram from './components/SystemDiagram'
import KvDiagram from './components/KvDiagram'
import MotionSection from './components/Motion'
import Cpu from './components/Cpu'
import Correctness from './components/Correctness'
import Operations from './components/Operations'
import Problems from './components/Problems'
import Negatives from './components/Negatives'
import { Method, Limitations, Reproduce } from './components/Method'

export default function App() {
  return (
    <div className="shell">
      <Sidebar />
      <main id="main" className="content">
        <Hero />
        <Results />
        <Load />
        <Journey />
        <SystemDiagram />
        <KvDiagram />
        <MotionSection />
        <Cpu />
        <Correctness />
        <Operations />
        <Problems />
        <Negatives />
        <Method />
        <Limitations />
        <Reproduce />
        <footer className="foot">
          llm-serve. A from-scratch inference server built to measure scheduling and memory management, not to compete with production systems.
        </footer>
      </main>
    </div>
  )
}
