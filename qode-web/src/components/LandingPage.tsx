import React, { useRef, useEffect } from 'react';
import { ArrowRight, ChevronDown, FileCode, Folder, Box, Zap, GitBranch, Search } from 'lucide-react';

interface LandingPageProps {
  onContinue: () => void;
}

// Node type colors — exactly matching graph explorer (index.css --color-node-*)
const NODE_TYPES = [
  { label: 'File',      color: '#3b82f6', bg: 'rgba(59,130,246,0.12)',  border: 'rgba(59,130,246,0.35)',  icon: FileCode  },
  { label: 'Folder',    color: '#6366f1', bg: 'rgba(99,102,241,0.12)',  border: 'rgba(99,102,241,0.35)',  icon: Folder    },
  { label: 'Class',     color: '#f59e0b', bg: 'rgba(245,158,11,0.12)',  border: 'rgba(245,158,11,0.35)',  icon: Box       },
  { label: 'Function',  color: '#10b981', bg: 'rgba(16,185,129,0.12)',  border: 'rgba(16,185,129,0.35)',  icon: Zap       },
  { label: 'Interface', color: '#ec4899', bg: 'rgba(236,72,153,0.12)',  border: 'rgba(236,72,153,0.35)',  icon: GitBranch },
  { label: 'Method',    color: '#14b8a6', bg: 'rgba(20,184,166,0.12)',  border: 'rgba(20,184,166,0.35)',  icon: Search    },
];

const FEATURE_CARDS = [
  {
    title:  'Visual Graph Explorer',
    desc:   'Navigate your entire codebase as an interactive dependency graph. Files, classes, and functions rendered as live nodes.',
    color:  '#3b82f6',
    bg:     'rgba(59,130,246,0.08)',
    border: 'rgba(59,130,246,0.3)',
    icon:   FileCode,
  },
  {
    title:  'AI-Powered Insights',
    desc:   'Ask questions in plain English. Qode grounds answers in your actual code and highlights relevant nodes in the graph.',
    color:  '#f59e0b',
    bg:     'rgba(245,158,11,0.08)',
    border: 'rgba(245,158,11,0.3)',
    icon:   Box,
  },
  {
    title:  'Semantic Search',
    desc:   'Find exactly what you need. Context-aware vector search surfaces the right function, class, or file instantly.',
    color:  '#10b981',
    bg:     'rgba(16,185,129,0.08)',
    border: 'rgba(16,185,129,0.3)',
    icon:   Zap,
  },
  {
    title:  'Blast Radius Analysis',
    desc:   'See exactly what breaks if you change X. Trace call chains and dependency paths before you refactor.',
    color:  '#ec4899',
    bg:     'rgba(236,72,153,0.08)',
    border: 'rgba(236,72,153,0.3)',
    icon:   GitBranch,
  },
  {
    title:  'Folder Structure',
    desc:   'Drill into your project hierarchy. Expand and collapse folder nodes to focus on any subsystem.',
    color:  '#6366f1',
    bg:     'rgba(99,102,241,0.08)',
    border: 'rgba(99,102,241,0.3)',
    icon:   Folder,
  },
  {
    title:  'Method Tracing',
    desc:   'Follow the full call graph from entry point to leaf method, across files and modules, in one view.',
    color:  '#14b8a6',
    bg:     'rgba(20,184,166,0.08)',
    border: 'rgba(20,184,166,0.3)',
    icon:   Search,
  },
];

export const LandingPage: React.FC<LandingPageProps> = ({ onContinue }) => {
  const homeRef  = useRef<HTMLElement>(null);
  const aboutRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (window.location.pathname === '/about') {
      setTimeout(() => aboutRef.current?.scrollIntoView({ behavior: 'instant' }), 50);
    } else if (window.location.pathname === '/' || window.location.pathname === '') {
      window.history.replaceState(null, '', '/home');
    }

    const observerOptions = { root: null, rootMargin: '-40% 0px -40% 0px', threshold: 0 };

    const observerCallback: IntersectionObserverCallback = (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          if (entry.target === homeRef.current  && window.location.pathname !== '/home')  window.history.replaceState(null, '', '/home');
          if (entry.target === aboutRef.current && window.location.pathname !== '/about') window.history.replaceState(null, '', '/about');
        }
      });
    };

    const observer = new IntersectionObserver(observerCallback, observerOptions);
    if (homeRef.current)  observer.observe(homeRef.current);
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

      {/* ── Hero ─────────────────────────────────────────────────── */}
      <section ref={homeRef} className="relative min-h-screen flex items-center justify-center p-8 lg:p-16">
        <div className="max-w-7xl mx-auto w-full grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">

          {/* Left content */}
          <div className="flex flex-col space-y-8 animate-slide-up">
            <div className="space-y-4">
              <h1 className="text-5xl lg:text-7xl font-bold tracking-tight">
                Understand Code <br />
                <span className="text-accent">At the Speed of Thought</span>
              </h1>
              <p className="text-xl text-text-secondary max-w-lg leading-relaxed">
                Qode is an intelligent, graph-based code exploration platform that turns complex
                repositories into an interactive, visual knowledge base.
              </p>
            </div>

            {/* Node-type pill legend */}
            <div className="flex flex-wrap gap-2">
              {NODE_TYPES.map(({ label, color, bg, border, icon: Icon }) => (
                <span
                  key={label}
                  style={{ color, background: bg, borderColor: border }}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold border"
                >
                  <Icon size={11} />
                  {label}
                </span>
              ))}
            </div>

            <div className="flex items-center space-x-4">
              <button
                id="hero-upload-btn"
                onClick={handleContinue}
                className="flex items-center px-6 py-3 bg-accent text-void font-semibold rounded-lg hover:bg-white transition-colors duration-200"
              >
                Upload Project
                <ArrowRight className="ml-2 w-5 h-5" />
              </button>
              <button
                id="hero-learn-more-btn"
                onClick={scrollToAbout}
                className="px-6 py-3 border border-border-subtle text-text-secondary font-medium rounded-lg hover:bg-surface hover:text-text-primary transition-colors duration-200"
              >
                Learn More
              </button>
            </div>
          </div>

          {/* Right – Logo */}
          <div className="flex justify-center items-center lg:justify-end">
            <div className="relative w-64 h-64 lg:w-96 lg:h-96">
              <div className="absolute inset-0 bg-accent rounded-full blur-3xl opacity-20 animate-breathe animate-pulse-glow" />
              <img
                src="/logo.png"
                alt="Qode Logo"
                className="relative z-10 w-full h-full object-contain drop-shadow-[0_0_20px_rgba(229,229,229,0.3)]"
              />
            </div>
          </div>
        </div>

        {/* Scroll indicator */}
        <div className="absolute bottom-8 left-1/2 transform -translate-x-1/2 animate-bounce">
          <button onClick={scrollToAbout} className="text-text-muted hover:text-text-primary transition-colors">
            <ChevronDown className="w-8 h-8" />
          </button>
        </div>
      </section>

      {/* ── About ────────────────────────────────────────────────── */}
      <section ref={aboutRef} className="bg-deep border-t border-border-subtle py-24 px-8 lg:px-16">
        <div className="max-w-6xl mx-auto space-y-20">

          {/* Heading */}
          <div className="text-center space-y-4">
            <h2 className="text-4xl font-bold">What is Qode?</h2>
            <p className="text-xl text-text-secondary max-w-2xl mx-auto">
              Qode parses your codebase and builds a rich knowledge graph — nodes for every file,
              folder, class, function, interface, and method, each with its own distinct color so
              you always know what you're looking at.
            </p>
          </div>

          {/* Color-coded node type showcase */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4">
            {NODE_TYPES.map(({ label, color, bg, border, icon: Icon }) => (
              <div
                key={label}
                style={{ background: bg, borderColor: border }}
                className="flex flex-col items-center gap-3 p-5 rounded-xl border text-center hover:scale-105 transition-transform duration-200"
              >
                <span style={{ color, background: `${color}22` }} className="p-2.5 rounded-lg">
                  <Icon size={22} />
                </span>
                <span style={{ color }} className="text-sm font-semibold">{label}</span>
              </div>
            ))}
          </div>

          {/* Feature cards – each uses a unique node color */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURE_CARDS.map(({ title, desc, color, bg, border, icon: Icon }) => (
              <div
                key={title}
                style={{ background: bg, borderColor: border }}
                className="group p-8 rounded-xl border transition-all duration-300 hover:scale-[1.02]"
              >
                <div className="flex items-center gap-3 mb-4">
                  <span style={{ color, background: `${color}22` }} className="p-2 rounded-lg">
                    <Icon size={20} />
                  </span>
                  <h3 style={{ color }} className="text-lg font-semibold">{title}</h3>
                </div>
                <p className="text-text-muted text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>

          {/* CTA */}
          <div className="text-center">
            <button
              id="about-get-started-btn"
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
