import React, { useEffect, useState } from 'react';
import { supabase } from './supabaseClient';
import './index.css';
import CheckEvent from './Check_Event';
import Rating from './Rating';
import PhysicalEvent from './Physical_Event';
import About from './about';
const SEARCH_API = import.meta.env.VITE_SEARCH_API_URL || 'http://127.0.0.1:8000';
const RATING_API = import.meta.env.VITE_RATING_API_URL || 'http://127.0.0.1:8002';
const CATEGORIES = [
  'All', 'Key Deadlines', 'Design Teams', 'Competitions', 'Residence Events',
  'Academic Events', 'Clubs', 'Career & Job Fairs', 'Recreation', 'Sports',
  'Workshops & Learning', 'Tech & Entrepreneurship', 'Arts & Culture',
  'Community', 'Social Events', 'General'
];

function App() {
  const [session, setSession] = useState(null);
  const [activeTab, setActiveTab] = useState('main');
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [timeFilter, setTimeFilter] = useState('all');
  const [scopeFilter, setScopeFilter] = useState('all');
  const [categoryFilter, setCategoryFilter] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [organizerMap, setOrganizerMap] = useState({});

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => setSession(session));
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => subscription.unsubscribe();
  }, []);

  useEffect(() => {
    if (session) {
      fetchEvents();
      fetchOrganizers();
    }
  }, [session, timeFilter, scopeFilter, categoryFilter, searchQuery]);

  const fetchOrganizers = async () => {
    try {
      const res = await fetch(`${RATING_API}/organizers`);
      if (res.ok) {
        const data = await res.json();
        const map = {};
        for (const org of (data.organizers || [])) {
          map[org.id] = org;
        }
        setOrganizerMap(map);
      }
    } catch (err) {
      console.error('Could not fetch organizers for event cards', err);
    }
  };

  const fetchEvents = async () => {
    try {
      setLoading(true); setError('');
      const params = new URLSearchParams({
        time_filter: timeFilter,
        scope: scopeFilter,
        category: categoryFilter,
        q: searchQuery,
        limit: '500',
      });
      const res = await fetch(`${SEARCH_API}/events?${params.toString()}`);
      if (!res.ok) throw new Error(`Search backend returned HTTP ${res.status}`);
      const payload = await res.json();
      const fetchedEvents = payload.events || [];
      fetchedEvents.sort((a, b) => {
        if (!a.date) return 1;
        if (!b.date) return -1;
        return a.date.localeCompare(b.date);
      });
      setEvents(fetchedEvents);
    } catch (err) {
      console.error(err);
      setError('Could not connect to search.py. Start the search backend on port 8000.');
      setEvents([]);
    } finally { setLoading(false); }
  };

  const renderStars = (score) => {
    const rounded = Math.round(score);
    return "★".repeat(rounded) + "☆".repeat(5 - rounded);
  };

  const formatDate = (value) => {
    if (!value) return '';
    const m = String(value).match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m) return value;
    return new Intl.DateTimeFormat('en-CA', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })
      .format(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  };
  const formatTime = (value) => {
    if (!value) return '';
    const m = String(value).match(/^(\d{1,2}):(\d{2})/);
    if (!m) return value;
    return new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit', hour12: true })
      .format(new Date(2000, 0, 1, Number(m[1]), Number(m[2])));
  };

  const signInWithGoogle = async () => {
    const { error } = await supabase.auth.signInWithOAuth({ 
      provider: 'google',
      options: {
        redirectTo: window.location.origin
      }
    });
    if (error) console.error('Error logging in:', error.message);
  };
  const signOut = async () => {
    const { error } = await supabase.auth.signOut();
    if (error) console.error('Error signing out:', error.message);
  };
  const clearFilters = () => {
    setTimeFilter('all'); setScopeFilter('all'); setCategoryFilter('All'); setSearchQuery('');
  };

  const buttonStyle = (active) => ({
    padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', color: '#fff',
    border: active ? '2px solid #fff' : '1px solid var(--glass-border)',
    background: active ? 'rgba(255,255,255,0.14)' : 'transparent'
  });
  const selectStyle = {
    padding: '10px', borderRadius: '8px', background: 'rgba(255,255,255,0.08)',
    color: '#fff', border: '1px solid var(--glass-border)', minWidth: '220px'
  };

  if (!session) {
    return <div className="app-container" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <div className="glass" style={{ textAlign: 'center', maxWidth: '400px' }}>
        <h1>UniEvent</h1>
        <p style={{ color: 'var(--text-muted)', marginBottom: '2rem' }}>Navigate University of Waterloo and Waterloo-area events with ease.</p>
        <button className="btn-google" onClick={signInWithGoogle}>
          <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="Google logo" style={{ width: '20px' }} /> Sign in with Google
        </button>
      </div>
    </div>;
  }

  return <div className="app-container">
    <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
        <h1 style={{ margin: 0, fontSize: '2rem' }}>UniEvent</h1>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <button onClick={() => setActiveTab('main')} style={{ background: activeTab === 'main' ? 'rgba(255,255,255,0.2)' : 'transparent', color: '#fff', border: '1px solid var(--glass-border)', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}>Main</button>
          <button onClick={() => setActiveTab('check')} style={{ background: activeTab === 'check' ? 'rgba(255,255,255,0.2)' : 'transparent', color: '#fff', border: '1px solid var(--glass-border)', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}>Check Event</button>
          <button onClick={() => setActiveTab('rating')} style={{ background: activeTab === 'rating' ? 'rgba(255,255,255,0.2)' : 'transparent', color: '#fff', border: '1px solid var(--glass-border)', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}>Organizers & Ratings</button>
          <button onClick={() => setActiveTab('physical')} style={{ background: activeTab === 'physical' ? 'rgba(255,255,255,0.2)' : 'transparent', color: '#fff', border: '1px solid var(--glass-border)', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}>Upload Event</button>
          <button onClick={() => setActiveTab('about')} style={{ background: activeTab === 'about' ? 'rgba(255,255,255,0.2)' : 'transparent', color: '#fff', border: '1px solid var(--glass-border)', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}>About</button>
        </div>
      </div>
      <button onClick={signOut} style={{ background: 'transparent', color: '#fff', border: '1px solid var(--glass-border)', padding: '8px 16px', borderRadius: '4px', cursor: 'pointer' }}>Sign Out</button>
    </header>

    {activeTab === 'main' ? (
      <>
        <section className="glass" style={{ padding: '1rem', marginBottom: '2rem' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', marginBottom: '12px' }}>
        <button style={buttonStyle(timeFilter === 'before')} onClick={() => setTimeFilter(timeFilter === 'before' ? 'all' : 'before')}>Event Before</button>
        <button style={buttonStyle(timeFilter === 'recent15')} onClick={() => setTimeFilter(timeFilter === 'recent15' ? 'all' : 'recent15')}>Event Recently in 15 Days</button>
        <button style={buttonStyle(timeFilter === 'future')} onClick={() => setTimeFilter(timeFilter === 'future' ? 'all' : 'future')}>Future Events</button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center', marginBottom: '12px' }}>
        <label style={{ fontWeight: 600 }}>Event Type:</label>
        <select value={scopeFilter} onChange={(e) => setScopeFilter(e.target.value)} style={selectStyle}>
          <option value="all">All</option><option value="uwaterloo">In UWaterloo</option><option value="outside">Outside UWaterloo</option>
        </select>
        <label style={{ fontWeight: 600, marginLeft: '8px' }}>Specific Breakdown:</label>
        <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)} style={selectStyle}>
          {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button onClick={clearFilters} style={{ ...buttonStyle(false), padding: '10px 14px' }}>Clear Filters</button>
      </div>

      <input type="search" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} placeholder="Search events..." aria-label="Search events"
        style={{ width: '100%', boxSizing: 'border-box', padding: '12px 14px', borderRadius: '8px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff', outline: 'none', fontSize: '1rem' }} />
    </section>

    {error && <div className="glass" style={{ padding: '12px 16px', marginBottom: '1rem', color: '#ffb4b4' }}>{error}</div>}
    <div style={{ marginBottom: '1rem', color: 'var(--text-muted)' }}>Showing {events.length} event{events.length === 1 ? '' : 's'}</div>

    {loading ? <p style={{ textAlign: 'center' }}>Loading events...</p> :
      <div className="event-grid">
        {events.length ? events.map((evt, idx) => {
          const org = evt.organizer_id ? organizerMap[evt.organizer_id] : null;
          return <div key={evt.id || evt.link_to_external || idx} className="glass event-card">
          {evt.image && <img src={evt.image} alt={evt.text} className="event-image" />}
          <h3 className="event-title">{evt.text}</h3>
          {(evt.date || evt.time || evt.location) && <div className="event-meta" style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '1rem', color: 'var(--text-muted)', fontSize: '0.92rem' }}>
            {evt.date && <div><strong>Date:</strong> {formatDate(evt.date)}</div>}
            {evt.time && <div><strong>Time:</strong> {formatTime(evt.time)}</div>}
            {evt.location && <div><strong>Location:</strong> {evt.location}</div>}
          </div>}
          {org && <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '1rem', padding: '8px 12px', borderRadius: '6px', background: 'rgba(255, 179, 71, 0.1)', border: '1px solid rgba(255, 179, 71, 0.25)' }}>
            <strong style={{ color: '#ffb347' }}>Organizer:</strong>
            <span>{org.name}</span>
            {org.review_count > 0 && <span style={{ color: '#ffb347', marginLeft: '4px' }}>{renderStars(org.average_rating)} ({org.average_rating.toFixed(1)})</span>}
          </div>}
          <p className="event-desc">{evt.description}</p>
          {evt.link_to_external && <a href={evt.link_to_external} target="_blank" rel="noopener noreferrer" className="event-link">View Event &rarr;</a>}
        </div>;
        }) : <p style={{ textAlign: 'center', gridColumn: '1 / -1' }}>No events match the current filters.</p>}
      </div>}
      </>
    ) : activeTab === 'check' ? (
      <CheckEvent />
    ) : activeTab === 'rating' ? (
      <Rating session={session} />
    ) : activeTab === 'about' ? (
      <About />
    ) : (
      <PhysicalEvent />
    )}
  </div>;
}

export default App;
