import React, { useEffect } from 'react';

const LandingPortalPage: React.FC = () => {
  useEffect(() => {
    window.location.replace('/showcase/');
  }, []);

  return (
    <div style={{ minHeight: '100vh', background: '#020617', color: '#f8fafc', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      Redirecting to MRIAgent showcase...
    </div>
  );
};

export default LandingPortalPage;
