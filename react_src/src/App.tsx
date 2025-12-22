// src/App.tsx
import React, { useEffect, useState, createContext, useContext } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import AdminPanel from './pages/AdminPanel';
import Account from './pages/Account';
import Reporting from './pages/Reporting';
import ContinuousMonitoringPage from './pages/continuous_monitoring';
import ExecutiveDashboards from './pages/executive_dashboards'; // <-- NEW

import './App.css';

// ─── Auth Context ─────────────────────────────────────────────
interface AuthContextType {
  isAuthed: boolean;
  setIsAuthed: (authed: boolean) => void;
  isAdmin: boolean;
  setIsAdmin: (admin: boolean) => void;
}

const AuthContext = createContext<AuthContextType>({
  isAuthed: false,
  setIsAuthed: () => {},
  isAdmin: false,
  setIsAdmin: () => {},
});

export const useAuth = () => useContext(AuthContext);

// ─── Wrapper for page transitions ─────────────────────────────
const PageWrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <motion.div
    initial={{ opacity: 0, y: 20 }}
    animate={{ opacity: 1, y: 0 }}
    exit={{ opacity: 0, y: -20 }}
    transition={{ duration: 0.4 }}
    style={{ width: '100%', height: '100%' }}
  >
    {children}
  </motion.div>
);

function App() {
  const [isAuthed, setIsAuthed] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const [checkedSession, setCheckedSession] = useState(false);
  const location = useLocation();

  useEffect(() => {
    fetch('/api/session', { credentials: 'include' })
      .then(res => res.json())
      .then(data => {
        setIsAuthed(!!data.authenticated);
        setIsAdmin(!!data.is_admin);
        setCheckedSession(true);
      })
      .catch(() => {
        setIsAuthed(false);
        setIsAdmin(false);
        setCheckedSession(true);
      });
  }, []);

  if (!checkedSession) return null; // or a loader

  return (
    <AuthContext.Provider value={{ isAuthed, setIsAuthed, isAdmin, setIsAdmin }}>
      <AnimatePresence mode="wait">
        <Routes location={location} key={location.pathname}>
          {/* root redirect */}
          <Route
            path="/"
            element={
              <PageWrapper>
                {isAuthed ? <Navigate to="/dashboard" /> : <Navigate to="/login" />}
              </PageWrapper>
            }
          />

          {/* public login */}
          <Route
            path="/login"
            element={
              <PageWrapper>
                <Login />
              </PageWrapper>
            }
          />

          {/* protected dashboard */}
          <Route
            path="/dashboard"
            element={
              <PageWrapper>
                {isAuthed ? <Dashboard /> : <Navigate to="/login" />}
              </PageWrapper>
            }
          />

          {/* protected continuous monitoring */}
          <Route
            path="/continuous_monitoring"
            element={
              <PageWrapper>
                {isAuthed ? <ContinuousMonitoringPage /> : <Navigate to="/login" />}
              </PageWrapper>
            }
          />

          {/* protected admin panel (client-side guard; server also enforces) */}
          <Route
            path="/admin"
            element={
              <PageWrapper>
                {isAuthed ? (isAdmin ? <AdminPanel /> : <Navigate to="/dashboard" />) : (
                  <Navigate to="/login" />
                )}
              </PageWrapper>
            }
          />

          {/* protected account */}
          <Route
            path="/account"
            element={
              <PageWrapper>
                {isAuthed ? <Account /> : <Navigate to="/login" />}
              </PageWrapper>
            }
          />

          {/* protected reporting */}
          <Route
            path="/reporting"
            element={
              <PageWrapper>
                {isAuthed ? <Reporting /> : <Navigate to="/login" />}
              </PageWrapper>
            }
          />

          {/* protected executive dashboards */}
          <Route
            path="/executive_dashboards"
            element={
              <PageWrapper>
                {isAuthed ? <ExecutiveDashboards /> : <Navigate to="/login" />}
              </PageWrapper>
            }
          />

          {/* catch-all */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AnimatePresence>
    </AuthContext.Provider>
  );
}

export default App;



