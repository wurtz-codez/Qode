import React, { useRef, useEffect } from 'react';
import { ArrowRight, ChevronDown } from 'lucide-react';

interface LandingPageProps {
  onContinue: () => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onContinue }) => {
  const homeRef = useRef<HTMLElement>(null);
  const aboutRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (window.location.pathname === '/about') {
      setTimeout(() => aboutRef.current?.scrollIntoView({ behavior: 'instant' }), 50);
    } else if (window.location.pathname === '/' || window.location.pathname === '') {
      window.history.replaceState(null, '', '/home');
    }

    const observerOptions = {
      root: null,
      rootMargin: '-40% 0px -40% 0px',
      threshold: 0,
    };

    const observerCallback: IntersectionObserverCallback = (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          if (entry.target === homeRef.current && window.location.pathname !== '/home') {
            window.history.replaceState(null, '', '/home');
          } else if (entry.target === aboutRef.current && window.location.pathname !== '/about') {
            window.history.replaceState(null, '', '/about');
          }
        }
      });
    };

    const observer = new IntersectionObserver(observerCallback, observerOptions);
    if (homeRef.current) observer.observe(homeRef.current);
    if (aboutRef.current) observer.observe(aboutRef.current);

    return () => observer.disconnect();
  }, []);

  const scrollToAbout = () => {
    aboutRef.current?.scrollIntoView({ behavior: 'smooth' });
    window.history.pushState(null, '', '/about');
  };

  const handleContinue = () => {
    window.history.pushState(null, '', '/app');
    onContinue();
  };

  return (
    <div className="min-h-screen bg-void text-text-primary font-sans overflow-y-auto overflow-x-hidden scrollbar-thin">
      {/* Hero Section */}
      <section ref={homeRef} className="relative min-h-screen flex items-center justify-center p-8 lg:p-16">
        <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">

          {/* Left Content */}
          <div className="flex flex-col space-y-8 animate-slide-up">
            <div className="space-y-4">
              <h1 className="text-5xl lg:text-7xl font-bold tracking-tight">
                Understand Code <br />
                <span className="text-accent">At the Speed of Thought</span>
              </h1>
              <p className="text-xl text-text-secondary max-w-lg leading-relaxed">
                Qode is an intelligent, graph-based code exploration platform that turns complex repositories into an interactive, visual knowledge base.
              </p>
            </div>

            <div className="flex items-center space-x-4">
              <button
                onClick={handleContinue}
                className="flex items-center px-6 py-3 bg-accent text-void font-semibold rounded-lg hover:bg-white transition-colors duration-200"
              >
                Upload Project
                <ArrowRight className="ml-2 w-5 h-5" />
              </button>
              <button
                onClick={scrollToAbout}
                className="px-6 py-3 border border-border-subtle text-text-secondary font-medium rounded-lg hover:bg-surface hover:text-text-primary transition-colors duration-200"
              >
                Learn More
              </button>
            </div>
          </div>

          {/* Right Content - Logo */}
          <div className="flex justify-center items-center lg:justify-end">
            <div className="relative w-64 h-64 lg:w-96 lg:h-96 ">
              <div className="absolute inset-0 bg-accent rounded-full blur-3xl opacity-20 animate-breathe animate-pulse-glow"></div>
              <img
                src="/logo.png"
                alt="Qode Logo"
                className="relative z-10 w-full h-full object-contain drop-shadow-[0_0_20px_rgba(229,229,229,0.3)]"
              />
            </div>
          </div>
        </div>

        {/* Scroll Indicator */}
        <div className="absolute bottom-8 left-1/2 transform -translate-x-1/2 animate-bounce">
          <button onClick={scrollToAbout} className="text-text-muted hover:text-text-primary transition-colors">
            <ChevronDown className="w-8 h-8" />
          </button>
        </div>
      </section>

      {/* About Section */}
      <section ref={aboutRef} className="min-h-screen bg-deep flex items-center justify-center p-8 lg:p-16 border-t border-border-subtle">
        <div className="max-w-4xl mx-auto space-y-16">
          <div className="text-center space-y-4">
            <h2 className="text-4xl font-bold">What is Qode?</h2>
            <p className="text-xl text-text-secondary">
              Qode parses your codebase and builds a detailed dependency graph, allowing you to visually explore relationships, classes, functions, and files.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div className="bg-surface p-8 rounded-xl border border-border-subtle hover:border-accent transition-colors duration-300">
              <h3 className="text-xl font-semibold mb-4 text-accent">Visual Exploration</h3>
              <p className="text-text-muted">
                Navigate through your project's architecture with an interactive graph interface. See how files and components connect in real-time.
              </p>
            </div>
            <div className="bg-surface p-8 rounded-xl border border-border-subtle hover:border-accent transition-colors duration-300">
              <h3 className="text-xl font-semibold mb-4 text-accent">AI-Powered Insights</h3>
              <p className="text-text-muted">
                Leverage local or cloud LLMs to ask questions about your codebase, understand complex logic, and find where changes are needed.
              </p>
            </div>
            <div className="bg-surface p-8 rounded-xl border border-border-subtle hover:border-accent transition-colors duration-300">
              <h3 className="text-xl font-semibold mb-4 text-accent">Semantic Search</h3>
              <p className="text-text-muted">
                Find exactly what you're looking for with context-aware semantic search that understands the meaning behind your code.
              </p>
            </div>
          </div>

          <div className="text-center">
            <button
              onClick={handleContinue}
              className="inline-flex items-center px-8 py-4 bg-accent text-void font-bold text-lg rounded-xl hover:bg-white transition-all duration-200 transform hover:scale-105 shadow-[0_0_20px_rgba(229,229,229,0.3)]"
            >
              Get Started Now
              <ArrowRight className="ml-3 w-6 h-6" />
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};
