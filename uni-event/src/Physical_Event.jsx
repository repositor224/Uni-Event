import React, { useState, useEffect } from 'react';
import { supabase } from './supabaseClient';
import './index.css';

const PHYSICAL_API = import.meta.env.VITE_PHYSICAL_API_URL || (import.meta.env.PROD ? '' : 'http://127.0.0.1:8003');
const RATING_API = import.meta.env.VITE_RATING_API_URL || (import.meta.env.PROD ? '' : 'http://127.0.0.1:8002');

const CATEGORIES = [
  'Key Deadlines', 'Design Teams', 'Competitions', 'Residence Events',
  'Academic Events', 'Clubs', 'Career & Job Fairs', 'Recreation', 'Sports',
  'Workshops & Learning', 'Tech & Entrepreneurship', 'Arts & Culture',
  'Community', 'Social Events', 'General'
];

const PhysicalEvent = () => {
  const [formData, setFormData] = useState({
    text: '',
    description: '',
    date: '',
    time: '',
    location: '',
    category: '',
    organizer_id: ''
  });
  const [posterFile, setPosterFile] = useState(null);
  const [posterPreview, setPosterPreview] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [submitMessage, setSubmitMessage] = useState('');
  const [organizers, setOrganizers] = useState([]);
  const [myEvents, setMyEvents] = useState([]);

  useEffect(() => {
    fetchOrganizers();
    fetchMyEvents();
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

  const fetchMyEvents = async () => {
    try {
      const res = await fetch(`${PHYSICAL_API}/physical_events`);
      if (res.ok) {
        const data = await res.json();
        setMyEvents(data.events || []);
      }
    } catch (err) {
      console.error('Failed to fetch physical events', err);
    }
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setPosterFile(file);
      const reader = new FileReader();
      reader.onloadend = () => setPosterPreview(reader.result);
      reader.readAsDataURL(file);
    }
  };

  const uploadPoster = async (file) => {
    const fileExt = file.name.split('.').pop();
    const fileName = `poster_${Date.now()}.${fileExt}`;
    const { data, error } = await supabase.storage.from('posters').upload(fileName, file);
    if (error) throw new Error(`Upload failed: ${error.message}`);
    const { data: urlData } = supabase.storage.from('posters').getPublicUrl(fileName);
    return urlData.publicUrl;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!formData.text.trim() || !formData.description.trim()) {
      setSubmitMessage('Event title and description are required.');
      return;
    }
    setUploading(true);
    setSubmitMessage('Uploading event...');

    try {
      let imageUrl = '';
      if (posterFile) {
        try {
          imageUrl = await uploadPoster(posterFile);
        } catch (err) {
          console.error('Poster upload failed:', err);
          setSubmitMessage(`Poster upload failed: ${err.message}. Please check that the "posters" storage bucket exists in Supabase and has public upload policies.`);
          setUploading(false);
          return;
        }
      }

      const payload = {
        ...formData,
        image_url: imageUrl || null
      };

      const res = await fetch(`${PHYSICAL_API}/physical_events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        setSubmitMessage('Event created successfully! It will now appear on the Main page.');
        setFormData({ text: '', description: '', date: '', time: '', location: '', category: '', organizer_id: '' });
        setPosterFile(null);
        setPosterPreview(null);
        fetchMyEvents();
      } else {
        const errText = await res.text();
        setSubmitMessage(`Error creating event: ${errText}`);
      }
    } catch (err) {
      setSubmitMessage('Could not connect to Physical Event backend.');
      console.error(err);
    } finally {
      setUploading(false);
    }
  };

  const inputStyle = {
    width: '100%', boxSizing: 'border-box', padding: '10px',
    borderRadius: '4px', border: '1px solid var(--glass-border)',
    background: 'rgba(255,255,255,0.08)', color: '#fff', fontFamily: 'inherit'
  };
  const labelStyle = { fontWeight: 'bold', display: 'block', marginBottom: '8px' };
  const groupStyle = { marginBottom: '20px' };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '2rem' }}>
      {/* Left: Create Form */}
      <div className="glass" style={{ padding: '2rem' }}>
        <h2 style={{ marginTop: 0 }}>Upload a Physical Event</h2>
        <p style={{ color: 'var(--text-muted)', marginBottom: '1.5rem' }}>
          Create your own event with a poster. It will appear on the Main events page for everyone to see.
        </p>
        <form onSubmit={handleSubmit}>

          <div style={groupStyle}>
            <label style={labelStyle}>Event Title *</label>
            <input type="text" name="text" value={formData.text} onChange={handleChange} placeholder="e.g. CS Club Workshop" style={inputStyle} />
          </div>

          <div style={groupStyle}>
            <label style={labelStyle}>Description *</label>
            <textarea name="description" value={formData.description} onChange={handleChange}
              placeholder="Describe your event in detail..."
              style={{ ...inputStyle, minHeight: '120px' }} />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '15px', ...groupStyle }}>
            <div>
              <label style={labelStyle}>Date</label>
              <input type="date" name="date" value={formData.date} onChange={handleChange} style={inputStyle} />
            </div>
            <div>
              <label style={labelStyle}>Time</label>
              <input type="time" name="time" value={formData.time} onChange={handleChange} style={inputStyle} />
            </div>
          </div>

          <div style={groupStyle}>
            <label style={labelStyle}>Location</label>
            <input type="text" name="location" value={formData.location} onChange={handleChange} placeholder="e.g. DC 1351" style={inputStyle} />
          </div>

          <div style={groupStyle}>
            <label style={labelStyle}>Category</label>
            <select name="category" value={formData.category} onChange={handleChange} style={inputStyle}>
              <option value="">Select Category (optional)</option>
              {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div style={groupStyle}>
            <label style={labelStyle}>Organizer</label>
            <select name="organizer_id" value={formData.organizer_id} onChange={handleChange} style={inputStyle}>
              <option value="">Select Organizer (optional)</option>
              {organizers.map(org => <option key={org.id} value={org.id}>{org.name}</option>)}
            </select>
          </div>

          <div style={groupStyle}>
            <label style={labelStyle}>Event Poster</label>
            <input type="file" accept="image/*" onChange={handleFileChange}
              style={{ ...inputStyle, padding: '8px' }} />
            {posterPreview && (
              <div style={{ marginTop: '10px' }}>
                <img src={posterPreview} alt="Poster preview" style={{ maxWidth: '100%', maxHeight: '200px', borderRadius: '8px', border: '1px solid var(--glass-border)' }} />
              </div>
            )}
          </div>

          <button type="submit" disabled={uploading || !formData.text.trim() || !formData.description.trim()}
            style={{
              padding: '12px 20px', borderRadius: '8px', cursor: 'pointer', color: '#fff',
              border: '1px solid var(--glass-border)', width: '100%',
              background: (uploading || !formData.text.trim() || !formData.description.trim()) ? 'transparent' : 'rgba(255,255,255,0.14)',
              opacity: (uploading || !formData.text.trim() || !formData.description.trim()) ? 0.5 : 1
            }}>
            {uploading ? 'Uploading...' : 'Create Event'}
          </button>
          {submitMessage && <p style={{ marginTop: '10px', textAlign: 'center' }}>{submitMessage}</p>}
        </form>
      </div>

      {/* Right: Previously uploaded events */}
      <div className="glass" style={{ padding: '1.5rem' }}>
        <h3 style={{ marginTop: 0 }}>User-Uploaded Events</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '15px', overflowY: 'auto' }}>
          {myEvents.length > 0 ? myEvents.map(evt => (
            <div key={evt.id} style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.05)' }}>
              {evt.image && <img src={evt.image} alt={evt.text} style={{ width: '100%', maxHeight: '120px', objectFit: 'cover', borderRadius: '6px', marginBottom: '8px' }} />}
              <div style={{ fontWeight: 'bold', fontSize: '1rem' }}>{evt.text}</div>
              {evt.date && <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{evt.date}</div>}
              {evt.location && <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>{evt.location}</div>}
            </div>
          )) : <p style={{ color: 'var(--text-muted)' }}>No user-uploaded events yet.</p>}
        </div>
      </div>
    </div>
  );
};

export default PhysicalEvent;
