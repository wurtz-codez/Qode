import { NodeLabel } from '../core/graph/types';

// Node colors by type — vivid, distinct hues matching the landing page legend
export const NODE_COLORS: Record<NodeLabel, string> = {
  Project:     '#ffffff',   // White  - root of everything, most prominent
  Package:     '#c084fc',   // Purple - major structural element
  Module:      '#818cf8',   // Indigo lighter - module container
  Folder:      '#6366f1',   // Indigo - folder nodes
  File:        '#3b82f6',   // Blue   - source files
  Class:       '#f59e0b',   // Amber  - class definitions
  Function:    '#10b981',   // Emerald - functions
  Method:      '#14b8a6',   // Teal   - methods
  Variable:    '#94a3b8',   // Slate  - muted, less important
  Interface:   '#ec4899',   // Pink   - interface definitions
  Enum:        '#f97316',   // Orange - enum definitions
  Decorator:   '#facc15',   // Yellow - decorators
  Import:      '#475569',   // Slate darker - very muted
  Type:        '#a78bfa',   // Violet light - type aliases
  CodeElement: '#64748b',   // Slate - generic, muted
  Community:   '#6366f1',   // Indigo light - cluster indicator
  Process:     '#f43f5e',   // Rose  - execution flow indicator
};

// Node sizes by type - clear visual hierarchy with dramatic size differences
// Structural nodes are MUCH larger to make hierarchy obvious
export const NODE_SIZES: Record<NodeLabel, number> = {
  Project: 20,     // Largest - root of everything
  Package: 16,     // Major structural element
  Module: 13,      // Important container
  Folder: 10,      // Structural - clearly bigger than files
  File: 6,         // Common element - smaller than folders
  Class: 8,        // Important code structure
  Function: 4,     // Common code element - small
  Method: 3,       // Smaller than function
  Variable: 2,     // Tiny - leaf node
  Interface: 7,    // Important type definition
  Enum: 5,         // Type definition
  Decorator: 2,    // Tiny modifier
  Import: 1.5,     // Very small - usually hidden anyway
  Type: 3,         // Type alias - small
  CodeElement: 2,  // Generic small
  Community: 0,    // Hidden by default - metadata node
  Process: 0,      // Hidden by default - metadata node
};

// Community color palette — vivid distinct hues for cluster-based coloring
export const COMMUNITY_COLORS = [
  '#f43f5e',   // Rose
  '#f97316',   // Orange
  '#facc15',   // Yellow
  '#10b981',   // Emerald
  '#06b6d4',   // Cyan
  '#3b82f6',   // Blue
  '#6366f1',   // Indigo
  '#a855f7',   // Purple
  '#ec4899',   // Pink
  '#14b8a6',   // Teal
  '#84cc16',   // Lime
  '#f59e0b',   // Amber
];

export const getCommunityColor = (communityIndex: number): string => {
  return COMMUNITY_COLORS[communityIndex % COMMUNITY_COLORS.length];
};

// Labels to show by default (hide imports and variables by default as they clutter)
export const DEFAULT_VISIBLE_LABELS: NodeLabel[] = [
  'Project',
  'Package',
  'Module',
  'Folder',
  'File',
  'Class',
  'Function',
  'Method',
  'Interface',
  'Enum',
  'Type',
];

// All filterable labels
export const FILTERABLE_LABELS: NodeLabel[] = [
  'Folder',
  'File',
  'Class',
  'Function',
  'Method',
  'Variable',
  'Interface',
  'Import',
];

// Edge/Relation types
export type EdgeType = 'CONTAINS' | 'DEFINES' | 'IMPORTS' | 'CALLS' | 'EXTENDS' | 'IMPLEMENTS';

export const ALL_EDGE_TYPES: EdgeType[] = [
  'CONTAINS',
  'DEFINES',
  'IMPORTS',
  'CALLS',
  'EXTENDS',
  'IMPLEMENTS',
];

// Default visible edges (CALLS hidden by default to reduce clutter)
export const DEFAULT_VISIBLE_EDGES: EdgeType[] = [
  'CONTAINS',
  'DEFINES',
  'IMPORTS',
  'EXTENDS',
  'IMPLEMENTS',
  'CALLS',
];

// Edge display info for UI — distinct colors per relationship type
export const EDGE_INFO: Record<EdgeType, { color: string; label: string }> = {
  CONTAINS:    { color: '#6366f1', label: 'Contains' },    // Indigo  - folder/file hierarchy
  DEFINES:     { color: '#3b82f6', label: 'Defines' },     // Blue    - file defines symbol
  IMPORTS:     { color: '#f59e0b', label: 'Imports' },     // Amber   - import dependency
  CALLS:       { color: '#10b981', label: 'Calls' },       // Emerald - function calls
  EXTENDS:     { color: '#f97316', label: 'Extends' },     // Orange  - inheritance
  IMPLEMENTS:  { color: '#ec4899', label: 'Implements' },  // Pink    - interface impl
};
