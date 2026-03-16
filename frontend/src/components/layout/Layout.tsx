import { Outlet } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'

export default function Layout() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <Header />
      <main className="ml-0 md:ml-sidebar mt-header p-4 md:p-6 flex-1 min-h-[calc(100vh-var(--spacing-header))]">
        <Outlet />
      </main>
    </div>
  )
}
