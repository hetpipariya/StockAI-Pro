import { useState, useEffect } from 'react';

const BREAKPOINTS = {
  mobile: 768,
  tablet: 1024,
  desktop: 1440,
};

export const useResponsive = () => {
  const [breakpoint, setBreakpoint] = useState(null);

  useEffect(() => {
    const handleResize = () => {
      const width = window.innerWidth;
      if (width < BREAKPOINTS.mobile) {
        setBreakpoint('mobile');
      } else if (width < BREAKPOINTS.tablet) {
        setBreakpoint('tablet');
      } else {
        setBreakpoint('desktop');
      }
    };

    handleResize();

    let timeoutId = null;
    const debouncedResize = () => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(handleResize, 250);
    };

    window.addEventListener('resize', debouncedResize);
    return () => {
      window.removeEventListener('resize', debouncedResize);
      clearTimeout(timeoutId);
    };
  }, []);

  return breakpoint;
};