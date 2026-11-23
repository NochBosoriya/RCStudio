"use client";

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Download,
  Mic2,
  Image as ImageIcon,
  Scissors,
  Calendar,
  FolderOpen,
  Plus,
  Settings,
  Play,
  CheckCircle,
  AlertCircle,
  Clock,
  Sparkles,
  Layers,
  Volume2,
  Video,
  Share2,
  RefreshCw,
  ChevronRight,
  Sliders,
  Trash2,
  XCircle
} from 'lucide-react';
import { api, downloadApi, DownloadJob, CreateDownloadRequest, ApiError } from '@/lib/api';

export default function AppShell() {
  const [activeTab, setActiveTab] = useState<'download' | 'translate' | 'overlay' | 'export' | 'publish'>('download');
  const [currentProject, setCurrentProject] = useState({ id: 'proj-1', name: 'My First Short Drama - Ep 1' });
  const [projects, setProjects] = useState([
    { id: 'proj-1', name: 'My First Short Drama - Ep 1' },
    { id: 'proj-2', name: 'CEO Boss Romance - Ep 1-5' }
  ]);
  const [newProjectName, setNewProjectName] = useState('');
  const [showNewProjectModal, setShowNewProjectModal] = useState(false);

  // Download Hub state
  const [downloadUrl, setDownloadUrl] = useState('');
  const [downloadPlatform, setDownloadPlatform] = useState<'youtube' | 'hongguo' | 'douyin'>('youtube');
  const [downloadJobs, setDownloadJobs] = useState<DownloadJob[]>([]);
  const [isLoadingJobs, setIsLoadingJobs] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  // Polling interval refs
  const pollingIntervals = useRef<Map<string, NodeJS.Timeout>>(new Map());

  // Translate & Dub Studio state
  const [transcriptLines, setTranscriptLines] = useState([
    { id: 'line-1', start: '00:01:20', end: '00:01:25', speaker: 'Speaker 1', source: '总裁驾驶Kawasaki H2去见李明', display: 'ប្រធានក្រុមហ៊ុន驾驶Kawasaki H2去见李明', tts_status: 'pending' },
    { id: 'line-2', start: '00:01:25', end: '00:01:30', speaker: 'Speaker 2', source: '我们必须在VIP会议室开会', display: 'យើងត្រូវតែប្រជុំនៅក្នុងVIPប្រជុំ', tts_status: 'synthesized' },
  ]);
  const [glossary, setGlossary] = useState([
    { id: 'g-1', source_term: '总裁', policy: 'TRANSLATE', display_name: 'ប្រធានក្រុមហ៊ុន', phonetic: '' },
    { id: 'g-2', source_term: 'Kawasaki H2', policy: 'KEEP_ORIGINAL', display_name: 'Kawasaki H2', phonetic: 'កាវ៉ាសាគី អេច ពីរ' },
    { id: 'g-3', source_term: '李明', policy: 'ROMANIZE_EN', display_name: 'Li Ming', phonetic: 'លី មីង' },
  ]);

  // Overlay / Thumbnail Editor state
  const [thumbnailTitle, setThumbnailTitle] = useState('KhmerDub Studio');
  const [thumbnailSubtitle, setThumbnailSubtitle] = useState('Episode 1 - HD Dubbed');
  const [thumbnailBgColor, setThumbnailBgColor] = useState('#1e293b');
  const [watermarkOpacity, setWatermarkOpacity] = useState(0.4);

  // Export & Splitter state
  const [exportPlatform, setExportPlatform] = useState('tiktok');
  const [splitDuration, setSplitDuration] = useState(60); // seconds

  // Publish & Scheduler state
  const [publishPlatforms, setPublishPlatforms] = useState({ tiktok: true, youtube: true, telegram: false });
  const [scheduleTime, setScheduleTime] = useState('');

  // Load download jobs on mount and when project changes
  const loadDownloadJobs = useCallback(async () => {
    if (!currentProject?.id) return;
    setIsLoadingJobs(true);
    setDownloadError(null);
    try {
      // Backend returns assets, not jobs. We'll use assets and check their status.
      // For now, we just set empty jobs since there's no dedicated jobs listing endpoint.
      // The jobs created in this session will be tracked in state.
      setDownloadJobs([]);
    } catch (error) {
      const message = error instanceof ApiError ? error.message : 'Failed to load download jobs';
      setDownloadError(message);
      console.error('Failed to load download jobs:', error);
    } finally {
      setIsLoadingJobs(false);
    }
  }, [currentProject?.id]);

  // Poll for job status updates
  const startPolling = useCallback((jobId: string) => {
    if (pollingIntervals.current.has(jobId)) return;

    const interval = setInterval(async () => {
      try {
        const status = await downloadApi.getStatus(jobId);
        setDownloadJobs(prev => prev.map(job =>
          job.id === parseInt(jobId, 10)
            ? { ...job, ...status }
            : job
        ));

        // Stop polling if completed or failed
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(interval);
          pollingIntervals.current.delete(jobId);
        }
      } catch (error) {
        console.error(`Polling failed for job ${jobId}:`, error);
        clearInterval(interval);
        pollingIntervals.current.delete(jobId);
      }
    }, 2000);

    pollingIntervals.current.set(jobId, interval);
  }, [pollingIntervals]);

  const stopPolling = useCallback((jobId: string) => {
    const interval = pollingIntervals.current.get(jobId);
    if (interval) {
      clearInterval(interval);
      pollingIntervals.current.delete(jobId);
    }
  }, [pollingIntervals]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      pollingIntervals.current.forEach(interval => clearInterval(interval));
      pollingIntervals.current.clear();
    };
  }, []);

  // Load jobs when project changes
  useEffect(() => {
    loadDownloadJobs();
  }, [loadDownloadJobs]);

  const handleCreateProject = (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjectName.trim()) return;
    const newProj = { id: `proj-${Date.now()}`, name: newProjectName };
    setProjects([...projects, newProj]);
    setCurrentProject(newProj);
    setNewProjectName('');
    setShowNewProjectModal(false);
  };

  const startDownload = async () => {
    if (!downloadUrl || !currentProject?.id) return;

    setDownloadError(null);
    try {
      const response = await downloadApi.create({
        urls: [downloadUrl],
        project_id: parseInt(currentProject.id.replace('proj-', ''), 10),
      } as CreateDownloadRequest);

      // Backend returns { job_id: number, status: "started" }
      // Create a temporary job entry and start polling
      const newJob: DownloadJob = {
        id: response.job_id,
        project_id: parseInt(currentProject.id.replace('proj-', ''), 10),
        url: downloadUrl,
        status: 'pending',
        progress: 0,
        message: 'Queued',
        created_at: new Date().toISOString(),
      };

      // Add the new job to the list
      setDownloadJobs(prev => [newJob, ...prev]);
      setDownloadUrl('');

      // Start polling for this job
      startPolling(response.job_id.toString());
    } catch (error) {
      const message = error instanceof ApiError
        ? `Download failed: ${error.message}`
        : 'Failed to start download. Please try again.';
      setDownloadError(message);
      console.error('Download failed:', error);
    }
  };

  const cancelDownload = async (jobId: string) => {
    try {
      await downloadApi.cancel(jobId);
      stopPolling(jobId);
      setDownloadJobs(prev => prev.map(job =>
        job.id === Number(jobId) ? { ...job, status: 'failed' as const, message: 'Cancelled by user' } : job
      ));
    } catch (error) {
      console.error('Failed to cancel download:', error);
      setDownloadError('Failed to cancel download');
    }
  };

  const deleteDownload = async (jobId: string) => {
    try {
      await downloadApi.delete(jobId);
      stopPolling(jobId);
      setDownloadJobs(prev => prev.filter(job => job.id !== Number(jobId)));
    } catch (error) {
      console.error('Failed to delete download:', error);
      setDownloadError('Failed to delete download');
    }
  };

  const formatDuration = (seconds: number): string => {
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hrs > 0) return `${hrs}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  const formatDate = (isoString: string): string => {
    return new Date(isoString).toLocaleString();
  };

  return (
    <div className="flex h-screen bg-slate-950 text-slate-100 font-sans overflow-hidden">
      {/* Sidebar - Project Navigation */}
      <div className="w-72 bg-slate-900 border-r border-slate-800 flex flex-col">
        {/* Brand Header */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-tr from-indigo-500 to-rose-500 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
              KH
            </div>
            <div>
              <h1 className="font-bold text-slate-100 tracking-tight">KhmerDub Studio</h1>
              <p className="text-xs text-slate-400">Video Localization Platform</p>
            </div>
          </div>
        </div>

        {/* Project Selector */}
        <div className="p-4 border-b border-slate-800">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active Project</span>
            <button
              onClick={() => setShowNewProjectModal(true)}
              className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center space-x-1"
            >
              <Plus className="w-3.5 h-3.5" />
              <span>New</span>
            </button>
          </div>
          <div className="bg-slate-950 rounded-lg p-2.5 border border-slate-800 flex items-center justify-between">
            <div className="flex items-center space-x-2 truncate">
              <FolderOpen className="w-4 h-4 text-indigo-400 flex-shrink-0" />
              <span className="text-sm font-medium truncate">{currentProject.name}</span>
            </div>
            <ChevronRight className="w-4 h-4 text-slate-500 flex-shrink-0" />
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          <button
            onClick={() => setActiveTab('download')}
            className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'download'
                ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 shadow-sm'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
            }`}
          >
            <Download className="w-4 h-4" />
            <span>1. Download Hub</span>
          </button>

          <button
            onClick={() => setActiveTab('translate')}
            className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'translate'
                ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 shadow-sm'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
            }`}
          >
            <Mic2 className="w-4 h-4" />
            <span>2. Translate & Dub Studio</span>
          </button>

          <button
            onClick={() => setActiveTab('overlay')}
            className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'overlay'
                ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 shadow-sm'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
            }`}
          >
            <ImageIcon className="w-4 h-4" />
            <span>3. Overlay & Thumbnail</span>
          </button>

          <button
            onClick={() => setActiveTab('export')}
            className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'export'
                ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 shadow-sm'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
            }`}
          >
            <Scissors className="w-4 h-4" />
            <span>4. Export & Splitter</span>
          </button>

          <button
            onClick={() => setActiveTab('publish')}
            className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === 'publish'
                ? 'bg-indigo-600/20 text-indigo-400 border border-indigo-500/30 shadow-sm'
                : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-200'
            }`}
          >
            <Calendar className="w-4 h-4" />
            <span>5. Publish & Scheduler</span>
          </button>
        </div>

        {/* Footer / System status */}
        <div className="p-4 border-t border-slate-800 bg-slate-900/50">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center space-x-1.5">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>API Connected</span>
            </span>
            <span className="font-mono text-indigo-400">v1.0.0</span>
          </div>
        </div>
      </div>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col overflow-hidden bg-slate-950">
        {/* Top Header Bar */}
        <header className="h-16 border-b border-slate-800 bg-slate-900/80 backdrop-blur px-6 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Sparkles className="w-5 h-5 text-indigo-400" />
            <h2 className="text-lg font-semibold text-slate-100 capitalize">
              {activeTab === 'download' && 'Download Hub — Multi-Platform Ingestion'}
              {activeTab === 'translate' && 'Translate & Dub Studio — Dual-Track & Voiceover'}
              {activeTab === 'overlay' && 'Overlay, Watermark & Thumbnail AI Editor'}
              {activeTab === 'export' && 'Export & Short Drama Splitter Studio'}
              {activeTab === 'publish' && 'Publish & Multi-Platform Scheduler'}
            </h2>
          </div>
          <div className="flex items-center space-x-3">
            <span className="px-3 py-1 bg-indigo-500/10 border border-indigo-500/20 rounded-full text-xs text-indigo-300 font-medium">
              Engine: Edge-TTS + F5-TTS
            </span>
          </div>
        </header>

        {/* Workspace Body */}
        <main className="flex-1 overflow-y-auto p-6">
          {/* TAB 1: DOWNLOAD HUB */}
          {activeTab === 'download' && (
            <div className="space-y-6 max-w-5xl mx-auto">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl">
                <h3 className="text-base font-semibold text-slate-200 mb-2">Ingest Video URL</h3>
                <p className="text-sm text-slate-400 mb-4">Paste a link from YouTube, TikTok, Douyin, or Hongguo Short Drama platform.</p>

                {downloadError && (
                  <div className="mb-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-lg text-sm text-rose-300 flex items-center justify-between">
                    <span>{downloadError}</span>
                    <button onClick={() => setDownloadError(null)} className="text-rose-400 hover:text-rose-300">
                      <XCircle className="w-4 h-4" />
                    </button>
                  </div>
                )}

                <div className="flex space-x-3">
                  <select
                    value={downloadPlatform}
                    onChange={(e) => setDownloadPlatform(e.target.value as 'youtube' | 'hongguo' | 'douyin')}
                    className="bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                    disabled={isLoadingJobs}
                  >
                    <option value="youtube">YouTube / General</option>
                    <option value="hongguo">Hongguo Short Drama</option>
                    <option value="douyin">Douyin / TikTok</option>
                  </select>

                  <input
                    type="text"
                    placeholder="https://www.youtube.com/watch?v=..."
                    value={downloadUrl}
                    onChange={(e) => setDownloadUrl(e.target.value)}
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                    disabled={isLoadingJobs}
                    onKeyDown={(e) => e.key === 'Enter' && startDownload()}
                  />

                  <button
                    onClick={startDownload}
                    disabled={!downloadUrl.trim() || isLoadingJobs}
                    className={`bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-all shadow-lg shadow-indigo-600/20 flex items-center space-x-2 ${!downloadUrl.trim() || isLoadingJobs ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    <Download className="w-4 h-4" />
                    <span>{isLoadingJobs ? 'Starting...' : 'Start Download'}</span>
                  </button>
                </div>
              </div>

              {/* Download Jobs Table */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl">
                <h3 className="text-base font-semibold text-slate-200 mb-4 flex items-center justify-between">
                  <span>Download Queue</span>
                  <span className="text-xs text-slate-400 font-normal">
                    {downloadJobs.length} job{downloadJobs.length !== 1 ? 's' : ''}
                    {isLoadingJobs && <span className="ml-2 text-indigo-400 flex items-center space-x-1"><RefreshCw className="w-3 h-3 animate-spin" /><span>Loading...</span></span>}
                  </span>
                </h3>

                {isLoadingJobs && downloadJobs.length === 0 ? (
                  <div className="text-center py-12 text-slate-500">
                    <RefreshCw className="w-10 h-10 mx-auto mb-3 opacity-40 animate-spin" />
                    <p className="text-sm">Loading download jobs...</p>
                  </div>
                ) : downloadJobs.length === 0 ? (
                  <div className="text-center py-12 text-slate-500 border border-dashed border-slate-800 rounded-lg">
                    <Video className="w-10 h-10 mx-auto mb-3 opacity-40" />
                    <p className="text-sm">No download jobs in queue.</p>
                    <p className="text-xs text-slate-500 mt-1">Paste a video URL above to start downloading.</p>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {downloadJobs.map(job => (
                      <div key={job.id} className="bg-slate-950 border border-slate-800 rounded-lg p-4 flex items-center justify-between">
                        <div className="space-y-1 flex-1 mr-4 min-w-0">
                          <div className="flex items-center space-x-2">
                            <span className="text-xs font-mono uppercase bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded border border-indigo-500/20">
                              {job.platform}
                            </span>
                            <span className="text-sm font-medium text-slate-200 truncate">{job.url}</span>
                          </div>
                          <p className="text-xs text-slate-400">{job.message}</p>
                          {job.videoInfo && (
                            <div className="flex items-center space-x-4 text-xs text-slate-500 mt-1">
                              <span>Duration: {formatDuration(job.videoInfo.duration)}</span>
                              <span>Added: {formatDate(job.created_at)}</span>
                            </div>
                          )}
                          <div className="w-full bg-slate-800 h-1.5 rounded-full overflow-hidden mt-2">
                            <div
                              className={`h-full transition-all duration-300 ${
                                job.status === 'completed' ? 'bg-emerald-500' :
                                job.status === 'failed' ? 'bg-rose-500' :
                                'bg-indigo-500'
                              }`}
                              style={{ width: `${job.progress}%` }}
                            ></div>
                          </div>
                        </div>
                        <div className="flex items-center space-x-2 flex-shrink-0">
                          {job.status === 'completed' ? (
                            <>
                              <span className="flex items-center space-x-1 text-xs text-emerald-400 bg-emerald-500/10 px-3 py-1 rounded-full border border-emerald-500/20">
                                <CheckCircle className="w-3.5 h-3.5" />
                                <span>Ready</span>
                              </span>
                              {job.filePath && (
                                <button className="text-xs text-indigo-400 hover:text-indigo-300 px-2 py-1 rounded bg-indigo-500/10 border border-indigo-500/20">
                                  Open Folder
                                </button>
                              )}
                            </>
                          ) : job.status === 'failed' ? (
                            <>
                              <span className="flex items-center space-x-1 text-xs text-rose-400 bg-rose-500/10 px-3 py-1 rounded-full border border-rose-500/20">
                                <AlertCircle className="w-3.5 h-3.5" />
                                <span>Failed</span>
                              </span>
                              <button
                                onClick={() => deleteDownload(job.id.toString())}
                                className="text-rose-400 hover:text-rose-300 p-1.5 rounded hover:bg-rose-500/10 transition-colors"
                                title="Delete job"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                              </button>
                            </>
                          ) : (
                            <>
                              <span className="flex items-center space-x-1 text-xs text-amber-400 bg-amber-500/10 px-3 py-1 rounded-full border border-amber-500/20">
                                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                                <span>{job.status === 'pending' ? 'Queued' : 'Downloading'}</span>
                              </span>
                              <button
                                onClick={() => cancelDownload(job.id.toString())}
                                className="text-amber-400 hover:text-amber-300 p-1.5 rounded hover:bg-amber-500/10 transition-colors"
                                title="Cancel download"
                              >
                                <XCircle className="w-3.5 h-3.5" />
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* TAB 2: TRANSLATE & DUB STUDIO */}
          {activeTab === 'translate' && (
            <div className="space-y-6 max-w-6xl mx-auto">
              {/* Pipeline Step Toolbar */}
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center space-x-3">
                  <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Pipeline:</span>
                  <button className="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 flex items-center space-x-1.5">
                    <Layers className="w-3.5 h-3.5 text-indigo-400" />
                    <span>1. Demucs Separate</span>
                  </button>
                  <button className="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 flex items-center space-x-1.5">
                    <Mic2 className="w-3.5 h-3.5 text-indigo-400" />
                    <span>2. Faster-Whisper Transcribe</span>
                  </button>
                  <button className="bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs px-3 py-1.5 rounded-lg border border-slate-700 flex items-center space-x-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                    <span>3. Entity Glossary & Guardrail</span>
                  </button>
                </div>
                <button className="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-4 py-2 rounded-lg font-medium shadow-md shadow-indigo-600/20">
                  Run Full Pipeline
                </button>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Transcript Editor (2 cols) */}
                <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-base font-semibold text-slate-200">Dual-Track Transcript & TTS Segments</h3>
                    <span className="text-xs text-slate-400 font-mono">2 lines loaded</span>
                  </div>

                  <div className="space-y-4 flex-1 overflow-y-auto max-h-[500px] pr-1">
                    {transcriptLines.map((line, idx) => (
                      <div key={line.id} className="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-3">
                        <div className="flex items-center justify-between text-xs text-slate-400">
                          <span className="font-mono text-indigo-400">{line.start} → {line.end} ({line.speaker})</span>
                          <span className="px-2 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                            {line.tts_status}
                          </span>
                        </div>
                        <div className="space-y-1">
                          <label className="text-[10px] uppercase font-semibold text-slate-500">Source (Chinese):</label>
                          <p className="text-sm font-medium text-slate-300 bg-slate-900 p-2 rounded border border-slate-800/80">{line.source}</p>
                        </div>
                        <div className="space-y-1">
                          <label className="text-[10px] uppercase font-semibold text-slate-500">Display / TTS (Khmer + Locked Tokens):</label>
                          <input
                            type="text"
                            value={line.display}
                            onChange={(e) => {
                              const updated = [...transcriptLines];
                              updated[idx].display = e.target.value;
                              setTranscriptLines(updated);
                            }}
                            className="w-full bg-slate-900 border border-slate-800 rounded px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Entity Glossary Manager (1 col) */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-base font-semibold text-slate-200">Entity Glossary</h3>
                    <button className="text-xs text-indigo-400 hover:text-indigo-300">+ Add Entity</button>
                  </div>

                  <div className="space-y-3 flex-1 overflow-y-auto max-h-[500px]">
                    {glossary.map((item) => (
                      <div key={item.id} className="bg-slate-950 border border-slate-800 rounded-lg p-3 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-bold text-slate-200">{item.source_term}</span>
                          <span className="text-[10px] font-mono px-1.5 py-0.5 bg-slate-800 text-slate-300 rounded border border-slate-700">
                            {item.policy}
                          </span>
                        </div>
                        <div className="text-xs text-indigo-300 font-medium">Display: {item.display_name}</div>
                        {item.phonetic && <div className="text-[11px] text-slate-400 font-mono">Phonetic: {item.phonetic}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 3: OVERLAY & THUMBNAIL */}
          {activeTab === 'overlay' && (
            <div className="space-y-6 max-w-6xl mx-auto">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Thumbnail Generator Spec */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-4">
                  <h3 className="text-base font-semibold text-slate-200">AI Thumbnail Generator Spec</h3>

                  <div className="space-y-3">
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Title Text</label>
                      <input
                        type="text"
                        value={thumbnailTitle}
                        onChange={(e) => setThumbnailTitle(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-slate-400 mb-1 block">Subtitle Text</label>
                      <input
                        type="text"
                        value={thumbnailSubtitle}
                        onChange={(e) => setThumbnailSubtitle(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                      />
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-xs text-slate-400 mb-1 block">Background Color</label>
                        <input
                          type="color"
                          value={thumbnailBgColor}
                          onChange={(e) => setThumbnailBgColor(e.target.value)}
                          className="w-full h-10 bg-slate-950 border border-slate-800 rounded-lg px-1 py-1 cursor-pointer"
                        />
                      </div>
                      <div>
                        <label className="text-xs text-slate-400 mb-1 block">Watermark Opacity: {watermarkOpacity}</label>
                        <input
                          type="range"
                          min="0.1"
                          max="1.0"
                          step="0.05"
                          value={watermarkOpacity}
                          onChange={(e) => setWatermarkOpacity(parseFloat(e.target.value))}
                          className="w-full mt-2 accent-indigo-500"
                        />
                      </div>
                    </div>
                  </div>

                  <button className="w-full bg-indigo-600 hover:bg-indigo-500 text-white py-2.5 rounded-lg text-sm font-medium transition-all shadow-lg shadow-indigo-600/20">
                    Generate Thumbnail
                  </button>
                </div>

                {/* Thumbnail Preview & Live Preview */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl flex flex-col items-center justify-center">
                  <h3 className="text-base font-semibold text-slate-200 mb-4 self-start">Live Thumbnail Preview (16:9)</h3>

                  <div
                    className="w-full aspect-video rounded-xl flex flex-col items-center justify-center p-6 text-center shadow-2xl relative overflow-hidden border border-slate-700"
                    style={{ backgroundColor: thumbnailBgColor }}
                  >
                    <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent"></div>
                    <div className="relative z-10 space-y-2">
                      <span className="px-3 py-1 bg-rose-600 text-white font-bold text-xs uppercase tracking-wider rounded shadow-md">
                        {thumbnailSubtitle}
                      </span>
                      <h2 className="text-2xl font-black text-white drop-shadow-lg tracking-tight">
                        {thumbnailTitle}
                      </h2>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* TAB 4: EXPORT & SPLITTER */}
          {activeTab === 'export' && (
            <div className="space-y-6 max-w-5xl mx-auto">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-6">
                <h3 className="text-base font-semibold text-slate-200">Short Drama Splitter & Vertical CROP</h3>
                <p className="text-sm text-slate-400">Automatically split full episodes into viral 60-second vertical TikTok/Shorts clips with burning subtitles and dynamic background framing.</p>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-2">
                    <label className="text-xs text-slate-400 block">Target Platform Aspect Ratio</label>
                    <select
                      value={exportPlatform}
                      onChange={(e) => setExportPlatform(e.target.value)}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                    >
                      <option value="tiktok">TikTok / Reels / Shorts (9:16 - 1080x1920)</option>
                      <option value="youtube">YouTube Landscape (16:9 - 1920x1080)</option>
                      <option value="telegram">Telegram HD (1:1 - 1080x1080)</option>
                    </select>
                  </div>

                  <div className="space-y-2">
                    <label className="text-xs text-slate-400 block">Split Duration (Seconds)</label>
                    <input
                      type="number"
                      value={splitDuration}
                      onChange={(e) => setSplitDuration(parseInt(e.target.value))}
                      className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>

                <button className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-all shadow-lg shadow-indigo-600/20 flex items-center space-x-2">
                  <Scissors className="w-4 h-4" />
                  <span>Run Batch Splitter & Render Clips</span>
                </button>
              </div>
            </div>
          )}

          {/* TAB 5: PUBLISH & SCHEDULER */}
          {activeTab === 'publish' && (
            <div className="space-y-6 max-w-5xl mx-auto">
              <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 shadow-xl space-y-6">
                <h3 className="text-base font-semibold text-slate-200">Automated Multi-Platform Scheduler</h3>
                <p className="text-sm text-slate-400">Schedule scheduled bulk uploads to TikTok, YouTube Shorts, and Telegram channels.</p>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <label className="bg-slate-950 border border-slate-800 rounded-xl p-4 flex items-center space-x-3 cursor-pointer hover:border-indigo-500/50 transition-all">
                    <input
                      type="checkbox"
                      checked={publishPlatforms.tiktok}
                      onChange={(e) => setPublishPlatforms({...publishPlatforms, tiktok: e.target.checked})}
                      className="w-4 h-4 accent-indigo-500 rounded"
                    />
                    <div>
                      <span className="text-sm font-medium text-slate-200 block">TikTok Studio</span>
                      <span className="text-xs text-slate-400">Auto-post vertical clips</span>
                    </div>
                  </label>

                  <label className="bg-slate-950 border border-slate-800 rounded-xl p-4 flex items-center space-x-3 cursor-pointer hover:border-indigo-500/50 transition-all">
                    <input
                      type="checkbox"
                      checked={publishPlatforms.youtube}
                      onChange={(e) => setPublishPlatforms({...publishPlatforms, youtube: e.target.checked})}
                      className="w-4 h-4 accent-indigo-500 rounded"
                    />
                    <div>
                      <span className="text-sm font-medium text-slate-200 block">YouTube Shorts</span>
                      <span className="text-xs text-slate-400">Schedule daily episodes</span>
                    </div>
                  </label>

                  <label className="bg-slate-950 border border-slate-800 rounded-xl p-4 flex items-center space-x-3 cursor-pointer hover:border-indigo-500/50 transition-all">
                    <input
                      type="checkbox"
                      checked={publishPlatforms.telegram}
                      onChange={(e) => setPublishPlatforms({...publishPlatforms, telegram: e.target.checked})}
                      className="w-4 h-4 accent-indigo-500 rounded"
                    />
                    <div>
                      <span className="text-sm font-medium text-slate-200 block">Telegram Channel</span>
                      <span className="text-xs text-slate-400">Broadcast video files</span>
                    </div>
                  </label>
                </div>

                <div className="space-y-2">
                  <label className="text-xs text-slate-400 block">Schedule Release Time</label>
                  <input
                    type="datetime-local"
                    value={scheduleTime}
                    onChange={(e) => setScheduleTime(e.target.value)}
                    className="bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <button className="bg-indigo-600 hover:bg-indigo-500 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-all shadow-lg shadow-indigo-600/20 flex items-center space-x-2">
                  <Share2 className="w-4 h-4" />
                  <span>Queue Scheduled Publishing</span>
                </button>
              </div>
            </div>
          )}
        </main>

        {/* New Project Modal */}
        {showNewProjectModal && (
          <div className="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50">
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 w-full max-w-md shadow-2xl space-y-4">
              <h3 className="text-lg font-bold text-slate-100">Create New Project</h3>
              <p className="text-sm text-slate-400">Enter a title for your short drama localization project.</p>
              <form onSubmit={handleCreateProject} className="space-y-4">
                <input
                  type="text"
                  placeholder="e.g. CEO Boss Romance - Episode 1"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-indigo-500"
                  autoFocus
                />
                <div className="flex justify-end space-x-3">
                  <button
                    type="button"
                    onClick={() => setShowNewProjectModal(false)}
                    className="px-4 py-2 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800 transition-all"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-5 py-2 rounded-lg text-sm font-medium bg-indigo-600 hover:bg-indigo-500 text-white shadow-lg shadow-indigo-600/20 transition-all"
                  >
                    Create Project
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}