import React from 'react';
import WUSA from "../../WUSA.png";

function About() {
  return (
    <div className="glass" style={{ padding: '2rem', marginBottom: '2rem', maxWidth: '800px', margin: '0 auto', color: '#fff' }}>
      <h2 style={{ fontSize: '2rem', marginBottom: '1rem' }}>What is UniEvent?</h2>
      <p style={{ lineHeight: '1.6', marginBottom: '1rem' }}>
        Have you been puzzled about finding an event that fits you? Have you been intrigued by having to search for 100 external events just to find the events you need? Have you attended an event but in the end realizing it is not your perfect fit? Don’t worry, we proudly introduce UniEvent. UniEvent is a student-led website that allows students to extract, pair and rate events by empowering through LLM so that students could find the events they liked about more efficiently. Events are very fun, so you should join a lot of them!! This is why I introduced this idea on Sept. 2025 and officially sharing it with you!
      </p>

      <p style={{ lineHeight: '1.6', marginBottom: '1.5rem' }}>
        We are extremely thankful for WUSA and the Change The Engine Competition Committee, who allows me to present this idea to everyone in the 2025-26 Change The Engine Competiton!
      </p>

      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '2rem' }}>
        <img
          src={WUSA}
          alt="WUSA Logo"
          style={{
            maxWidth: '300px',
            height: 'auto',
            borderRadius: '8px'
          }}
        />
      </div>

      <h3 style={{ fontSize: '1.5rem', marginBottom: '1rem' }}>Presentation Video</h3>
      <div style={{ position: 'relative', paddingBottom: '56.25%', height: 0, overflow: 'hidden', marginBottom: '2rem', borderRadius: '8px' }}>
        <iframe
          style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%' }}
          src="https://www.youtube.com/embed/oSKVqYqS4WA?start=7326"
          title="UniEvent Presentation"
          frameBorder="0"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
          allowFullScreen>
        </iframe>
      </div>

      <h3 style={{ fontSize: '1.5rem', marginBottom: '1rem' }}>Contact us/Support</h3>
      <p style={{ lineHeight: '1.6', marginBottom: '1.5rem' }}>
        We are a beginning startup and we would appreciate any input from anyone. If you have any questions, ideas or feedbacks, we are very welcome to hear from you! We are also looking for volunteers and collaborators for this startup. So if you are interested in contributing to the project, don’t hesitate to reach out as well!
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginBottom: '2rem' }}>
        <div>
          <strong style={{ display: 'block', color: '#ffb347' }}>Email</strong>
          <a href="mailto:t3zou@uwaterloo.ca" style={{ color: '#fff', textDecoration: 'underline' }}>t3zou@uwaterloo.ca</a>
        </div>
        <div>
          <strong style={{ display: 'block', color: '#ffb347' }}>Github Issues (For bug identification or feature advise)</strong>
          <a href="https://github.com/repositor224/Uni-Event.git" target="_blank" rel="noopener noreferrer" style={{ color: '#fff', textDecoration: 'underline' }}>
            https://github.com/repositor224/Uni-Event.git
          </a>
        </div>
        <div>
          <strong style={{ display: 'block', color: '#ffb347' }}>Support us!</strong>
          <a href="https://www.paypal.com/paypalme/ziyizou655" target="_blank" rel="noopener noreferrer" style={{ color: '#fff', textDecoration: 'underline' }}>
            https://www.paypal.com/paypalme/ziyizou655
          </a>
        </div>
      </div>
    </div>
  );
}

export default About;
