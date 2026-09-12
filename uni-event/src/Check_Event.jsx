import React, { useState } from 'react';
import './index.css';

const CHECK_API = import.meta.env.VITE_CHECK_API_URL || 'http://127.0.0.1:8001';

const CheckEvent = () => {
  const [formData, setFormData] = useState({
    introvertExtrovert: '',
    academicSocial: '',
    eventTypes: '',
    year: '',
    faculty: '',
    groupSize: '',
    startDate: '',
    endDate: ''
  });
  const [dateError, setDateError] = useState('');
  const [submitMessage, setSubmitMessage] = useState('');

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
  };

  const handleDateChange = (e) => {
    const { name, value } = e.target;
    setFormData(prev => {
      const newData = { ...prev, [name]: value };
      validateDates(newData.startDate, newData.endDate);
      return newData;
    });
  };

  const validateDates = (start, end) => {
    setDateError('');
    if (start && end) {
      const diffTime = new Date(end) - new Date(start);
      const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
      if (diffDays > 5) {
        setDateError('The difference between start and end date must be 5 days or less.');
      } else if (diffDays < 0) {
        setDateError('End date cannot be before start date.');
      }
    }
  };

  const [results, setResults] = useState([]);

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

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (dateError) return;
    setSubmitMessage('Submitting to LLM advisor (this may take a moment)...');
    setResults([]);
    try {
      const res = await fetch(`${CHECK_API}/check_events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });
      if (res.ok) {
        const payload = await res.json();
        setSubmitMessage('Preferences submitted successfully!');
        setResults(payload.events || []);
      } else {
        const errorText = await res.text();
        setSubmitMessage(`Error submitting preferences: ${errorText}`);
      }
    } catch (err) {
      setSubmitMessage('Could not connect to backend.');
    }
  };

  const radioLabelStyle = { marginRight: '15px', cursor: 'pointer' };
  const formGroupStyle = { marginBottom: '20px' };

  return (
    <div className="glass" style={{ padding: '2rem', maxWidth: '600px', margin: '0 auto' }}>
      <h2 style={{ marginTop: 0 }}>Event Preferences</h2>
      <form onSubmit={handleSubmit}>
        
        {/* Q1 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q1) Are you an introverted or extroverted person?</label>
          <div style={{ display: 'flex', gap: '10px' }}>
            <label style={radioLabelStyle}><input type="radio" name="introvertExtrovert" value="Introverted" onChange={handleChange} /> Introverted</label>
            <label style={radioLabelStyle}><input type="radio" name="introvertExtrovert" value="Extroverted" onChange={handleChange} /> Extroverted</label>
          </div>
        </div>

        {/* Q2 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q2) Do you prefer academic or social events?</label>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <label style={radioLabelStyle}><input type="radio" name="academicSocial" value="Academic" onChange={handleChange} /> Academic</label>
            <label style={radioLabelStyle}><input type="radio" name="academicSocial" value="Social" onChange={handleChange} /> Social</label>
            <label style={radioLabelStyle}><input type="radio" name="academicSocial" value="Both" onChange={handleChange} /> Both</label>
            <label style={radioLabelStyle}><input type="radio" name="academicSocial" value="Neither" onChange={handleChange} /> Neither</label>
          </div>
        </div>

        {/* Q3 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q3) What type of events do you like the most?</label>
          <input type="text" name="eventTypes" value={formData.eventTypes} onChange={handleChange} style={{ width: '100%', padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff' }} />
        </div>

        {/* Q4 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q4) What is your current year?</label>
          <select name="year" value={formData.year} onChange={handleChange} style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff', width: '100%' }}>
            <option value="">Select Year</option>
            <option value="First Year">First Year</option>
            <option value="Second Year">Second Year</option>
            <option value="Third Year">Third Year</option>
            <option value="Fourth Year">Fourth Year</option>
            <option value="Fifth Year">Fifth Year</option>
          </select>
        </div>

        {/* Q5 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q5) What is your faculty?</label>
          <select name="faculty" value={formData.faculty} onChange={handleChange} style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff', width: '100%' }}>
            <option value="">Select Faculty</option>
            <option value="Arts">Arts</option>
            <option value="Math">Math</option>
            <option value="Science">Science</option>
            <option value="Engineering">Engineering</option>
            <option value="Health">Health</option>
            <option value="Environment">Environment</option>
          </select>
        </div>

        {/* Q6 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q6) How large of a group do you prefer?</label>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <label style={radioLabelStyle}><input type="radio" name="groupSize" value="Small" onChange={handleChange} /> Small</label>
            <label style={radioLabelStyle}><input type="radio" name="groupSize" value="Medium" onChange={handleChange} /> Medium</label>
            <label style={radioLabelStyle}><input type="radio" name="groupSize" value="Large" onChange={handleChange} /> Large</label>
            <label style={radioLabelStyle}><input type="radio" name="groupSize" value="No preference" onChange={handleChange} /> No preference</label>
          </div>
        </div>

        {/* Q7 */}
        <div style={formGroupStyle}>
          <label style={{ fontWeight: 'bold', display: 'block', marginBottom: '8px' }}>(Q7) What is the date of events that you want to search?</label>
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <label style={{ fontSize: '0.85rem', marginBottom: '4px' }}>Start Date</label>
              <input type="date" name="startDate" value={formData.startDate} onChange={handleDateChange} style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <label style={{ fontSize: '0.85rem', marginBottom: '4px' }}>End Date</label>
              <input type="date" name="endDate" value={formData.endDate} onChange={handleDateChange} style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--glass-border)', background: 'rgba(255,255,255,0.08)', color: '#fff' }} />
            </div>
          </div>
          {dateError && <div style={{ color: '#ffb4b4', marginTop: '8px', fontSize: '0.9rem' }}>{dateError}</div>}
        </div>

        <button 
          type="submit" 
          disabled={!!dateError || !Object.values(formData).every(val => val.trim() !== '')} 
          style={{ padding: '10px 20px', borderRadius: '8px', cursor: 'pointer', color: '#fff', border: '1px solid var(--glass-border)', background: (!!dateError || !Object.values(formData).every(val => val.trim() !== '')) ? 'transparent' : 'rgba(255,255,255,0.14)', marginTop: '10px', width: '100%', opacity: (!!dateError || !Object.values(formData).every(val => val.trim() !== '')) ? 0.5 : 1 }}
        >
          Submit
        </button>
        {submitMessage && <p style={{ marginTop: '10px', textAlign: 'center' }}>{submitMessage}</p>}
      </form>

      {results.length > 0 && (
        <div style={{ marginTop: '30px' }}>
          <h3>Top Recommendations</h3>
          <div className="event-grid" style={{ gridTemplateColumns: '1fr' }}>
            {results.map((evt, idx) => (
              <div key={evt.id || evt.link_to_external || idx} className="glass event-card" style={{ background: 'rgba(255, 255, 255, 0.03)' }}>
                <h3 className="event-title">{evt.text}</h3>
                {(evt.date || evt.time || evt.location) && <div className="event-meta" style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '1rem', color: 'var(--text-muted)', fontSize: '0.92rem' }}>
                  {evt.date && <div><strong>Date:</strong> {formatDate(evt.date)}</div>}
                  {evt.time && <div><strong>Time:</strong> {formatTime(evt.time)}</div>}
                  {evt.location && <div><strong>Location:</strong> {evt.location}</div>}
                </div>}
                <p className="event-desc">{evt.description}</p>
                {evt.link_to_external && <a href={evt.link_to_external} target="_blank" rel="noopener noreferrer" className="event-link">View Event &rarr;</a>}
              </div>
            ))}
          </div>
        </div>
      )}

    </div>
  );
};

export default CheckEvent;
