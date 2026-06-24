import React, { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { AlertTriangle, CheckCircle, TrendingUp, Users, Zap } from 'lucide-react';

/**
 * SwarmTesting Component
 * 
 * Allows users to:
 * 1. Configure load test parameters (Burst, Ramp, Soak)
 * 2. Select user modes (Startup, Growth, Enterprise)
 * 3. Choose user journeys (E-commerce, Finance, SaaS)
 * 4. View real-time metrics and bottleneck analysis
 * 5. Generate Ship Report for business decision-making
 */

export default function SwarmTesting({ runId, onSwarmComplete }) {
  const [activeTab, setActiveTab] = useState('config');
  const [config, setConfig] = useState({
    profile: 'burst',
    user_mode: 'startup',
    journey_template: 'ecommerce',
    duration_secs: 60,
  });
  const [loading, setLoading] = useState(false);
  const [results, setResults] = useState(null);
  const [shipReport, setShipReport] = useState(null);
  const [error, setError] = useState(null);

  const profiles = [
    { value: 'burst', label: '⚡ Burst', desc: '0 → target instantly' },
    { value: 'ramp', label: '📈 Ramp', desc: 'Gradual increase' },
    { value: 'soak', label: '💧 Soak', desc: '12-hour sustained' },
  ];

  const modes = [
    { value: 'startup', label: '🚀 Startup', range: '10-500 users' },
    { value: 'growth', label: '📊 Growth', range: '1K-10K users' },
    { value: 'enterprise', label: '🏢 Enterprise', range: '25K-100K+ users' },
  ];

  const journeys = [
    { value: 'ecommerce', label: '🛒 E-commerce', flow: 'Browse → Cart → Checkout' },
    { value: 'finance', label: '💳 Finance', flow: 'Login → Payment → Transfer' },
    { value: 'saas', label: '⚙️ SaaS', flow: 'Signup → Dashboard → Create' },
  ];

  const handleStartTest = async () => {
    setLoading(true);
    setError(null);
    try {
      // Configure swarm test
      const configRes = await fetch(`/api/runs/${runId}/swarm/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      
      if (!configRes.ok) throw new Error('Failed to configure test');
      
      // Start test
      setActiveTab('monitoring');
      
      // Poll for results
      const checkResults = setInterval(async () => {
        const res = await fetch(`/api/runs/${runId}/swarm/results`);
        const data = await res.json();
        
        if (data.summary && data.summary.status === 'completed') {
          setResults(data.summary);
          clearInterval(checkResults);
          onSwarmComplete?.(data.summary);
        }
      }, 2000);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateShipReport = async () => {
    try {
      const res = await fetch(`/api/runs/${runId}/swarm/ship-report`, {
        method: 'POST',
      });
      const data = await res.json();
      setShipReport(data);
      setActiveTab('ship-report');
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="w-full space-y-6">
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="config">Configure</TabsTrigger>
          <TabsTrigger value="monitoring">Monitoring</TabsTrigger>
          <TabsTrigger value="results">Results</TabsTrigger>
          <TabsTrigger value="ship-report">Ship Report</TabsTrigger>
        </TabsList>

        {/* Configuration Tab */}
        <TabsContent value="config" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Swarm Load Testing Configuration</CardTitle>
              <CardDescription>
                Test how many concurrent users your app can handle and where the breaking points are
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Load Profile Selection */}
              <div>
                <label className="text-sm font-semibold mb-3 block">Load Profile</label>
                <div className="grid grid-cols-3 gap-3">
                  {profiles.map((p) => (
                    <button
                      key={p.value}
                      onClick={() => setConfig({ ...config, profile: p.value })}
                      className={`p-3 border rounded-lg text-left transition-all ${
                        config.profile === p.value
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="font-medium text-sm">{p.label}</div>
                      <div className="text-xs text-gray-600">{p.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* User Mode Selection */}
              <div>
                <label className="text-sm font-semibold mb-3 block">User Mode</label>
                <div className="grid grid-cols-3 gap-3">
                  {modes.map((m) => (
                    <button
                      key={m.value}
                      onClick={() => setConfig({ ...config, user_mode: m.value })}
                      className={`p-3 border rounded-lg text-left transition-all ${
                        config.user_mode === m.value
                          ? 'border-green-500 bg-green-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="font-medium text-sm">{m.label}</div>
                      <div className="text-xs text-gray-600">{m.range}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Journey Template Selection */}
              <div>
                <label className="text-sm font-semibold mb-3 block">User Journey</label>
                <div className="grid grid-cols-3 gap-3">
                  {journeys.map((j) => (
                    <button
                      key={j.value}
                      onClick={() => setConfig({ ...config, journey_template: j.value })}
                      className={`p-3 border rounded-lg text-left transition-all ${
                        config.journey_template === j.value
                          ? 'border-purple-500 bg-purple-50'
                          : 'border-gray-200 hover:border-gray-300'
                      }`}
                    >
                      <div className="font-medium text-sm">{j.label}</div>
                      <div className="text-xs text-gray-600">{j.flow}</div>
                    </button>
                  ))}
                </div>
              </div>

              {/* Duration */}
              <div>
                <label className="text-sm font-semibold mb-2 block">Test Duration</label>
                <div className="flex items-center gap-3">
                  <input
                    type="range"
                    min="30"
                    max="300"
                    value={config.duration_secs}
                    onChange={(e) => setConfig({ ...config, duration_secs: parseInt(e.target.value) })}
                    className="flex-1"
                  />
                  <span className="text-sm font-mono bg-gray-100 px-3 py-1 rounded">
                    {config.duration_secs}s
                  </span>
                </div>
              </div>

              {error && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Error</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              <Button
                onClick={handleStartTest}
                disabled={loading}
                className="w-full bg-blue-600 hover:bg-blue-700"
              >
                {loading ? 'Starting...' : 'Start Load Test'}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Monitoring Tab */}
        <TabsContent value="monitoring" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Real-Time Metrics</CardTitle>
              <CardDescription>
                Watching concurrent users and system response
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="p-4 bg-blue-50 border border-blue-200 rounded-lg">
                  <div className="text-sm text-gray-600">Concurrent Users</div>
                  <div className="text-3xl font-bold text-blue-600">
                    {results?.actual_concurrent || '—'}
                  </div>
                </div>
                <div className="p-4 bg-green-50 border border-green-200 rounded-lg">
                  <div className="text-sm text-gray-600">Success Rate</div>
                  <div className="text-3xl font-bold text-green-600">
                    {results?.success_rate ? `${(results.success_rate * 100).toFixed(1)}%` : '—'}
                  </div>
                </div>
                <div className="p-4 bg-orange-50 border border-orange-200 rounded-lg">
                  <div className="text-sm text-gray-600">P95 Latency</div>
                  <div className="text-3xl font-bold text-orange-600">
                    {results?.latency_p95 ? `${results.latency_p95.toFixed(0)}ms` : '—'}
                  </div>
                </div>
                <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                  <div className="text-sm text-gray-600">Error Rate</div>
                  <div className="text-3xl font-bold text-red-600">
                    {results?.error_rate ? `${results.error_rate.toFixed(1)}%` : '—'}
                  </div>
                </div>
              </div>

              {results && !results.completed && (
                <div className="p-4 bg-blue-50 border border-blue-300 rounded-lg text-center">
                  <div className="animate-pulse">Test in progress...</div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Results Tab */}
        <TabsContent value="results" className="space-y-4">
          {results ? (
            <>
              <Card>
                <CardHeader>
                  <CardTitle>Load Test Results</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm text-gray-600">Total Sessions</div>
                      <div className="text-2xl font-bold">{results.total_sessions}</div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600">Successful</div>
                      <div className="text-2xl font-bold text-green-600">
                        {results.successful_sessions}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600">Breaking Point</div>
                      <div className="text-2xl font-bold">
                        {results.breaking_point_users || 'Not reached'}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm text-gray-600">Revenue Risk/Hour</div>
                      <div className="text-2xl font-bold text-red-600">
                        ${results.revenue_impact_dollars?.toFixed(0) || 0}
                      </div>
                    </div>
                  </div>

                  {/* Latency breakdown */}
                  <div className="mt-6 p-4 bg-gray-50 rounded-lg">
                    <h4 className="font-semibold mb-3">Latency Percentiles</h4>
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span>P50</span>
                        <span className="font-mono font-bold">{results.latency_p50}ms</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span>P95</span>
                        <span className="font-mono font-bold">{results.latency_p95}ms</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span>P99</span>
                        <span className="font-mono font-bold">{results.latency_p99}ms</span>
                      </div>
                    </div>
                  </div>

                  <Button
                    onClick={handleGenerateShipReport}
                    className="w-full bg-purple-600 hover:bg-purple-700"
                  >
                    Generate Ship Report →
                  </Button>
                </CardContent>
              </Card>
            </>
          ) : (
            <Card>
              <CardContent className="py-8 text-center text-gray-600">
                No results yet. Run a load test to see results.
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* Ship Report Tab */}
        <TabsContent value="ship-report" className="space-y-4">
          {shipReport ? (
            <>
              {/* Readiness Status */}
              <Card className={`border-2 ${
                shipReport.readiness === 'ship_now' ? 'border-green-500 bg-green-50' :
                shipReport.readiness === 'warnings' ? 'border-yellow-500 bg-yellow-50' :
                'border-red-500 bg-red-50'
              }`}>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    {shipReport.readiness === 'ship_now' && (
                      <>
                        <CheckCircle className="h-6 w-6 text-green-600" />
                        <span>Ready to Ship!</span>
                      </>
                    )}
                    {shipReport.readiness === 'warnings' && (
                      <>
                        <AlertTriangle className="h-6 w-6 text-yellow-600" />
                        <span>Ship with Caution</span>
                      </>
                    )}
                    {shipReport.readiness === 'not_ready' && (
                      <>
                        <AlertTriangle className="h-6 w-6 text-red-600" />
                        <span>Not Ready Yet</span>
                      </>
                    )}
                  </CardTitle>
                  <CardDescription>
                    Confidence Score: {shipReport.confidence_score}/100
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm leading-relaxed">
                    {shipReport.executive_summary}
                  </p>
                </CardContent>
              </Card>

              {/* Key Questions */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Key Questions</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <div className="flex justify-between text-sm">
                    <span>Can users use it?</span>
                    <span className={shipReport.can_users_use_it ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>
                      {shipReport.can_users_use_it ? '✓ YES' : '✗ NO'}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span>Can disabled users use it?</span>
                    <span className={shipReport.can_disabled_users_use_it ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>
                      {shipReport.can_disabled_users_use_it ? '✓ YES' : '⚠ PARTIAL'}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span>Peak Capacity</span>
                    <span className="font-mono font-bold">
                      {shipReport.can_handle_peak_users.toLocaleString()} users
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span>Are payments working?</span>
                    <span className={shipReport.are_payments_working ? 'text-green-600 font-bold' : 'text-red-600 font-bold'}>
                      {shipReport.are_payments_working ? '✓ YES' : '✗ NO'}
                    </span>
                  </div>
                  <div className="flex justify-between text-sm">
                    <span>Checkout Abandonment Risk</span>
                    <span className={`font-bold ${
                      shipReport.checkout_abandonment_risk === 'low' ? 'text-green-600' :
                      shipReport.checkout_abandonment_risk === 'moderate' ? 'text-yellow-600' :
                      'text-red-600'
                    }`}>
                      {shipReport.checkout_abandonment_risk.toUpperCase()}
                    </span>
                  </div>
                </CardContent>
              </Card>

              {/* Issues & Recommendations */}
              {shipReport.launch_blockers.length > 0 && (
                <Alert variant="destructive">
                  <AlertTriangle className="h-4 w-4" />
                  <AlertTitle>Launch Blockers</AlertTitle>
                  <AlertDescription>
                    <ul className="list-disc list-inside mt-2">
                      {shipReport.launch_blockers.map((blocker, i) => (
                        <li key={i} className="text-sm">{blocker}</li>
                      ))}
                    </ul>
                  </AlertDescription>
                </Alert>
              )}

              {shipReport.recommendations.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Recommendations</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <ul className="space-y-2">
                      {shipReport.recommendations.map((rec, i) => (
                        <li key={i} className="text-sm flex gap-2">
                          <span className="text-blue-600">→</span>
                          <span>{rec}</span>
                        </li>
                      ))}
                    </ul>
                  </CardContent>
                </Card>
              )}
            </>
          ) : (
            <Card>
              <CardContent className="py-8 text-center text-gray-600">
                Generate a Ship Report from your test results.
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
