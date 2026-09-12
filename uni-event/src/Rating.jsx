import React, { useState, useEffect } from 'react';
import './index.css';

const RATING_API = import.meta.env.VITE_RATING_API_URL || 'http://127.0.0.1:8002';
const SEARCH_API = import.meta.env.VITE_SEARCH_API_URL || 'http://127.0.0.1:8000';

const Rating = ({ session }) => {
  const [organizers, setOrganizers] = useState([]);
  const [selectedOrg, setSelectedOrg] = useState(null);
  const [newOrgName, setNewOrgName] = useState('');
  const [loading, setLoading] = useState(false);

  // Reviews state
  const [reviews, setReviews] = useState([]);
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState('');

  // Events linking state
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [linkedEvents, setLinkedEvents] = useState([]);

  useEffect(() => {
    fetchOrganizers();
  }, []);

  const fetchOrganizers = async () => {
    try {
      const res = await fetch(`${RATING_API}/organizers`);
      if (res.ok) {
        const data = await res.json();
        setOrganizers(data.organizers || []);
      }
    } catch (err) {
      console.error('Failed to fetch organizers', err);
    }
  };

  const createOrganizer = async (e) => {
    e.preventDefault();
    if (!newOrgName.trim()) return;
    try {
      const res = await fetch(`${RATING_API}/organizers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: newOrgName })
      });
      if (res.ok) {
        setNewOrgName('');
        fetchOrganizers();
      }
    } catch (err) {
      console.error('Failed to create organizer', err);
    }
  };

  const selectOrganizer = (org) => {
    setSelectedOrg(org);
    fetchReviews(org.id);
    fetchLinkedEvents(org.id);
    setSearchResults([]);
    setSearchQuery('');
  };

  const fetchReviews = async (orgId) => {
    try {
      const res = await fetch(`${RATING_API}/organizers/${orgId}/reviews`);
      if (res.ok) {
        const data = await res.json();
        setReviews(data.reviews || []);
      }
    } catch (err) {
      console.error('Failed to fetch reviews', err);
    }
  };

  const submitReview = async (e) => {
    e.preventDefault();
    if (!session) return alert("Please sign in to leave a review.");
    if (!comment.trim()) return alert("Please enter a comment.");
    
    const userName = session.user?.user_metadata?.full_name || session.user?.email || 'Anonymous User';
    const userId = session.user?.id || 'unknown';

    try {
      const res = await fetch(`${RATING_API}/organizers/${selectedOrg.id}/reviews`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: userId,
          user_name: userName,
          rating,
          comment
        })
      });
      if (res.ok) {
        setComment('');
        setRating(5);
        fetchReviews(selectedOrg.id);
        fetchOrganizers(); // Refresh average ratings
      }
    } catch (err) {
      console.error('Failed to submit review', err);
    }
  };

  const searchEvents = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    try {
      setLoading(true);
      const params = new URLSearchParams({ q: searchQuery, limit: '10' });
      const res = await fetch(`${SEARCH_API}/events?${params.toString()}`);
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data.events || []);
      }
    } catch (err) {
      console.error('Search failed', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchLinkedEvents = async (orgId) => {
    try {
      const res = await fetch(`${RATING_API}/organizers/${orgId}/events`);
      if (res.ok) {
        const data = await res.json();
        setLinkedEvents(data.events || []);
      }
    } catch (err) {
      console.error('Failed to fetch linked events', err);
    }
  };

  const linkEvent = async (eventId) => {
    try {
      const res = await fetch(`${RATING_API}/events/link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: String(eventId), organizer_id: selectedOrg.id })
      });
      if (res.ok) {
        setSearchResults(searchResults.filter(evt => evt.id !== eventId));
        fetchLinkedEvents(selectedOrg.id);
      } else {
        const errData = await res.text();
        console.error('Link failed:', errData);
        alert(`Failed to link event: ${errData}`);
      }
    } catch (err) {
      console.error('Failed to link event', err);
      alert('Could not connect to Rating backend.');
    }
  };

  const renderStars = (score) => {
    return "★".repeat(Math.round(score)) + "☆".repeat(5 - Math.round(score));
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '2rem', height: '100%' }}>
      {/* Left Sidebar: Organizers List */}
      <div className="glass" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        <h2 style={{ margin: 0 }}>Event Organizers</h2>
        <form onSubmit={createOrganizer} style={{ display: 'flex', gap: '10px' }}>
          <input 
            type="text" 
            placeholder="New Organizer Name..." 
            value={newOrgName} 
            onChange={e => setNewOrgName(e.target.value)}
            style={{ flex: 1, padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff' }}
          />
          <button type="submit" style={{ padding: '8px 12px', borderRadius: '4px', background: 'rgba(255,255,255,0.14)', color: '#fff', border: '1px solid var(--glass-border)', cursor: 'pointer' }}>Add</button>
        </form>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '1rem', overflowY: 'auto' }}>
          {organizers.map(org => (
            <div 
              key={org.id} 
              onClick={() => selectOrganizer(org)}
              style={{ 
                padding: '12px', 
                borderRadius: '8px', 
                border: selectedOrg?.id === org.id ? '2px solid #fff' : '1px solid var(--glass-border)', 
                background: selectedOrg?.id === org.id ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.05)',
                cursor: 'pointer'
              }}
            >
              <div style={{ fontWeight: 'bold', fontSize: '1.1rem' }}>{org.name}</div>
              <div style={{ color: '#ffb347', fontSize: '0.9rem' }}>
                {org.review_count > 0 ? `${renderStars(org.average_rating)} (${org.average_rating.toFixed(1)})` : 'No ratings yet'}
              </div>
            </div>
          ))}
          {organizers.length === 0 && <p style={{ color: 'var(--text-muted)' }}>No organizers added yet.</p>}
        </div>
      </div>

      {/* Right Content: Selected Organizer Details */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
        {selectedOrg ? (
          <>
            <div className="glass" style={{ padding: '2rem' }}>
              <h2 style={{ marginTop: 0 }}>{selectedOrg.name}</h2>
              <div style={{ color: '#ffb347', fontSize: '1.2rem', marginBottom: '2rem' }}>
                {renderStars(selectedOrg.average_rating || 0)} <span style={{ color: '#fff', fontSize: '1rem' }}>({selectedOrg.review_count || 0} reviews)</span>
              </div>

              <h3>Write a Review</h3>
              <form onSubmit={submitReview} style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px' }}>Rating (1-5)</label>
                  <select value={rating} onChange={e => setRating(Number(e.target.value))} style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff', width: '100px' }}>
                    {[5,4,3,2,1].map(n => <option key={n} value={n}>{n} Stars</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px' }}>Comment</label>
                  <textarea 
                    value={comment} 
                    onChange={e => setComment(e.target.value)} 
                    placeholder={`Share your experience with ${selectedOrg.name}...`}
                    style={{ width: '100%', boxSizing: 'border-box', padding: '10px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff', minHeight: '80px', fontFamily: 'inherit' }}
                  />
                </div>
                <button type="submit" disabled={!comment.trim()} style={{ padding: '10px', borderRadius: '8px', background: !comment.trim() ? 'transparent' : 'rgba(255,255,255,0.14)', border: '1px solid var(--glass-border)', color: '#fff', cursor: 'pointer', opacity: !comment.trim() ? 0.5 : 1 }}>Submit Review</button>
              </form>
            </div>

            <div className="glass" style={{ padding: '2rem' }}>
              <h3 style={{ marginTop: 0 }}>User Reviews</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '15px' }}>
                {reviews.length > 0 ? reviews.map(rev => (
                  <div key={rev.id} style={{ borderBottom: '1px solid var(--glass-border)', paddingBottom: '15px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px' }}>
                      <strong style={{ color: '#fff' }}>{rev.user_name}</strong>
                      <span style={{ color: '#ffb347' }}>{renderStars(rev.rating)}</span>
                    </div>
                    <div style={{ color: 'var(--text-muted)' }}>{rev.comment}</div>
                    <div style={{ fontSize: '0.8rem', color: '#888', marginTop: '5px' }}>{new Date(rev.created_at).toLocaleDateString()}</div>
                  </div>
                )) : <p style={{ color: 'var(--text-muted)' }}>No reviews yet.</p>}
              </div>
            </div>

            <div className="glass" style={{ padding: '2rem' }}>
              <h3 style={{ marginTop: 0 }}>Link Hosted Events</h3>
              <p style={{ color: 'var(--text-muted)' }}>Search the database for existing events and attribute them to this organizer.</p>
              
              <form onSubmit={searchEvents} style={{ display: 'flex', gap: '10px', marginBottom: '20px' }}>
                <input 
                  type="text" 
                  placeholder="Search events..." 
                  value={searchQuery} 
                  onChange={e => setSearchQuery(e.target.value)}
                  style={{ flex: 1, padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff' }}
                />
                <button type="submit" style={{ padding: '8px 12px', borderRadius: '4px', background: 'rgba(255,255,255,0.14)', color: '#fff', border: '1px solid var(--glass-border)', cursor: 'pointer' }}>Search</button>
              </form>

              {loading && <p>Searching...</p>}
              
              {searchResults.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '20px', padding: '10px', border: '1px solid var(--glass-border)', borderRadius: '8px' }}>
                  <h4 style={{ margin: 0, color: '#fff' }}>Search Results</h4>
                  {searchResults.map(evt => (
                    <div key={evt.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '4px' }}>
                      <div>
                        <strong>{evt.text}</strong>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{evt.date ? evt.date.split('T')[0] : 'No date'}</div>
                      </div>
                      <button onClick={() => linkEvent(evt.id)} style={{ padding: '6px 12px', borderRadius: '4px', background: 'rgba(255,255,255,0.2)', border: 'none', color: '#fff', cursor: 'pointer' }}>Link Event</button>
                    </div>
                  ))}
                </div>
              )}

              <h4 style={{ marginTop: '20px', color: '#fff' }}>Currently Hosted Events</h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {linkedEvents.length > 0 ? linkedEvents.map(evt => (
                  <div key={evt.id} style={{ background: 'rgba(255,255,255,0.05)', padding: '10px', borderRadius: '4px' }}>
                    <strong>{evt.text}</strong>
                    <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{evt.date ? evt.date.split('T')[0] : 'No date'}</div>
                  </div>
                )) : <p style={{ color: 'var(--text-muted)' }}>No events currently linked to this organizer.</p>}
              </div>

            </div>
          </>
        ) : (
          <div className="glass" style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-muted)' }}>
            <h2>Select an organizer</h2>
            <p>Click on an event organizer from the list on the left to view ratings, read comments, or link their events.</p>
          </div>
        )}
      </div>
    </div>
  );
};

export default Rating;
