import { Route, Routes } from 'react-router'
import { RequireAuth } from './auth/RequireAuth.tsx'
import { HomePage } from './features/home/HomePage.tsx'
import { HomeSkeleton } from './features/home/HomeSkeleton.tsx'
import { LoginPage } from './features/login/LoginPage.tsx'

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage background={<HomeSkeleton />} />} />
      <Route
        path="*"
        element={
          <RequireAuth>
            <HomePage />
          </RequireAuth>
        }
      />
    </Routes>
  )
}
