import React, { useMemo, useState } from 'react';

/**
 * WIEP Mobile App MVP
 * Single-file Expo/React Native starter for warehouse workforce operations.
 *
 * Recommended runtime:
 * - Expo SDK 51+
 * - React Native + TypeScript
 *
 * Install deps in your app shell:
 *   npx create-expo-app wiep-mobile -t expo-template-blank-typescript
 *   npm i @expo/vector-icons
 *
 * Then replace App.tsx with this file.
 *
 * Notes:
 * - This is intentionally self-contained in one file for fast prototyping.
 * - In production, split into modules: /screens, /components, /api, /state, /theme.
 */

import {
  SafeAreaView,
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  Switch,
  Alert,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

type Role = 'worker' | 'supervisor';
type WorkerTab = 'home' | 'shifts' | 'clock' | 'performance' | 'profile';
type SupervisorTab = 'home' | 'live' | 'team' | 'approvals' | 'profile';

type Shift = {
  id: string;
  date: string;
  start: string;
  end: string;
  role: string;
  zone: string;
  status: 'assigned' | 'in_progress' | 'completed';
};

type AlertItem = {
  id: string;
  severity: 'low' | 'medium' | 'high';
  title: string;
  detail: string;
};

const workerShifts: Shift[] = [
  { id: 'S-1001', date: 'Mon 20 Apr', start: '06:00', end: '14:00', role: 'Picker', zone: 'Zone A', status: 'assigned' },
  { id: 'S-1002', date: 'Tue 21 Apr', start: '06:00', end: '14:00', role: 'Picker', zone: 'Zone C', status: 'assigned' },
  { id: 'S-1003', date: 'Wed 22 Apr', start: '14:00', end: '22:00', role: 'Packer', zone: 'Dispatch', status: 'assigned' },
];

const liveAlerts: AlertItem[] = [
  { id: 'A1', severity: 'high', title: 'Dispatch SLA risk', detail: 'Backlog rising 18% in Dispatch. Reassign 2 certified operators.' },
  { id: 'A2', severity: 'medium', title: 'Overtime threshold nearing', detail: 'Night shift in Zone B is projected to exceed overtime budget by 9%.' },
  { id: 'A3', severity: 'low', title: 'Certification expiry', detail: '3 forklift certifications expire within 14 days.' },
];

const teamData = [
  { name: 'Maria Chen', role: 'Picker', productivity: 112, status: 'Active' },
  { name: 'James Ali', role: 'Forklift', productivity: 97, status: 'Break' },
  { name: 'Talia Wong', role: 'Packer', productivity: 119, status: 'Active' },
  { name: 'Ben Kumar', role: 'Picker', productivity: 88, status: 'Idle' },
];

function App() {
  const [authenticated, setAuthenticated] = useState(false);
  const [role, setRole] = useState<Role>('worker');
  const [workerTab, setWorkerTab] = useState<WorkerTab>('home');
  const [supervisorTab, setSupervisorTab] = useState<SupervisorTab>('home');
  const [clockedIn, setClockedIn] = useState(false);
  const [onBreak, setOnBreak] = useState(false);
  const [biometricEnabled, setBiometricEnabled] = useState(true);
  const [email, setEmail] = useState('ops@warehouseco.com');
  const [password, setPassword] = useState('password');
  const [search, setSearch] = useState('');

  const activeTab = role === 'worker' ? workerTab : supervisorTab;

  const greeting = useMemo(() => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  }, []);

  const handleLogin = () => {
    if (!email || !password) {
      Alert.alert('Missing details', 'Enter email and password.');
      return;
    }
    setAuthenticated(true);
  };

  const handleClockAction = () => {
    if (!clockedIn) {
      setClockedIn(true);
      setOnBreak(false);
      Alert.alert('Clocked in', 'Shift started successfully.');
      return;
    }

    if (clockedIn && !onBreak) {
      setOnBreak(true);
      Alert.alert('Break started', 'Paid break timer started.');
      return;
    }

    setClockedIn(false);
    setOnBreak(false);
    Alert.alert('Clocked out', 'Shift completed and synced.');
  };

  const filteredTeam = teamData.filter((member) =>
    member.name.toLowerCase().includes(search.toLowerCase()) ||
    member.role.toLowerCase().includes(search.toLowerCase())
  );

  if (!authenticated) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.authContainer}>
          <View style={styles.authCard}>
            <View style={styles.brandRow}>
              <View style={styles.brandIcon}>
                <Ionicons name="cube-outline" size={26} color="#111827" />
              </View>
              <View>
                <Text style={styles.eyebrow}>WIEP Mobile</Text>
                <Text style={styles.authTitle}>Warehouse workforce app</Text>
              </View>
            </View>

            <Text style={styles.sectionText}>
              Role-based mobile access for workers and supervisors with live operations, clocking, schedules, and performance visibility.
            </Text>

            <View style={styles.segmentRow}>
              <SegmentButton label="Worker" selected={role === 'worker'} onPress={() => setRole('worker')} />
              <SegmentButton label="Supervisor" selected={role === 'supervisor'} onPress={() => setRole('supervisor')} />
            </View>

            <Label>Email</Label>
            <TextInput value={email} onChangeText={setEmail} style={styles.input} autoCapitalize="none" keyboardType="email-address" />
            <Label>Password</Label>
            <TextInput value={password} onChangeText={setPassword} style={styles.input} secureTextEntry />

            <View style={styles.preferenceRow}>
              <Text style={styles.preferenceLabel}>Enable biometric login</Text>
              <Switch value={biometricEnabled} onValueChange={setBiometricEnabled} />
            </View>

            <PrimaryButton label={`Sign in as ${role === 'worker' ? 'Worker' : 'Supervisor'}`} onPress={handleLogin} />
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.appShell}>
        <View style={styles.header}>
          <View>
            <Text style={styles.eyebrow}>{greeting}</Text>
            <Text style={styles.headerTitle}>{role === 'worker' ? 'Alex Parker' : 'Samir Patel'}</Text>
            <Text style={styles.headerSubtitle}>
              {role === 'worker' ? 'Morning shift • Truganina DC' : 'Supervisor • Dispatch & Packing'}
            </Text>
          </View>
          <Pressable style={styles.roleChip} onPress={() => setRole(role === 'worker' ? 'supervisor' : 'worker')}>
            <Ionicons name="swap-horizontal-outline" size={16} color="#111827" />
            <Text style={styles.roleChipText}>{role}</Text>
          </Pressable>
        </View>

        <ScrollView contentContainerStyle={styles.content}>
          {role === 'worker' && activeTab === 'home' && <WorkerHome clockedIn={clockedIn} onBreak={onBreak} />}
          {role === 'worker' && activeTab === 'shifts' && <WorkerShifts />}
          {role === 'worker' && activeTab === 'clock' && (
            <WorkerClock clockedIn={clockedIn} onBreak={onBreak} onClockAction={handleClockAction} />
          )}
          {role === 'worker' && activeTab === 'performance' && <WorkerPerformance />}
          {role === 'worker' && activeTab === 'profile' && <ProfileCard role={role} />}

          {role === 'supervisor' && activeTab === 'home' && <SupervisorHome />}
          {role === 'supervisor' && activeTab === 'live' && <SupervisorLive />}
          {role === 'supervisor' && activeTab === 'team' && <SupervisorTeam search={search} setSearch={setSearch} filteredTeam={filteredTeam} />}
          {role === 'supervisor' && activeTab === 'approvals' && <SupervisorApprovals />}
          {role === 'supervisor' && activeTab === 'profile' && <ProfileCard role={role} />}
        </ScrollView>

        {role === 'worker' ? (
          <BottomNav
            items={[
              { key: 'home', label: 'Home', icon: 'home-outline' },
              { key: 'shifts', label: 'Shifts', icon: 'calendar-outline' },
              { key: 'clock', label: 'Clock', icon: 'time-outline' },
              { key: 'performance', label: 'Perf', icon: 'bar-chart-outline' },
              { key: 'profile', label: 'Profile', icon: 'person-outline' },
            ]}
            activeKey={workerTab}
            onChange={(key) => setWorkerTab(key as WorkerTab)}
          />
        ) : (
          <BottomNav
            items={[
              { key: 'home', label: 'Home', icon: 'home-outline' },
              { key: 'live', label: 'Live', icon: 'pulse-outline' },
              { key: 'team', label: 'Team', icon: 'people-outline' },
              { key: 'approvals', label: 'Approve', icon: 'checkmark-done-outline' },
              { key: 'profile', label: 'Profile', icon: 'person-outline' },
            ]}
            activeKey={supervisorTab}
            onChange={(key) => setSupervisorTab(key as SupervisorTab)}
          />
        )}
      </View>
    </SafeAreaView>
  );
}

function WorkerHome({ clockedIn, onBreak }: { clockedIn: boolean; onBreak: boolean }) {
  return (
    <View style={styles.stackGap}>
      <HeroCard
        title={clockedIn ? (onBreak ? 'On break' : 'Shift active') : 'Ready to start'}
        subtitle={clockedIn ? 'Zone A • Picker • Target 110 UPH' : 'Next shift starts at 06:00 in Zone A'}
        statLabel="Today"
        statValue={clockedIn ? '4.2h' : '0.0h'}
      />

      <Section title="Today at a glance">
        <MetricsRow
          items={[
            { label: 'UPH', value: '108' },
            { label: 'Quality', value: '99.2%' },
            { label: 'Utilisation', value: '92%' },
          ]}
        />
      </Section>

      <Section title="Next actions">
        <ListItem icon="walk-outline" title="Start in Zone A" subtitle="Pick wave 4 begins at 06:15" />
        <ListItem icon="school-outline" title="Certification renewal" subtitle="Forklift refresher due in 12 days" />
        <ListItem icon="chatbubble-ellipses-outline" title="Manager note" subtitle="Good quality score yesterday. Maintain pace in Dispatch cross-cover." />
      </Section>
    </View>
  );
}

function WorkerShifts() {
  return (
    <View style={styles.stackGap}>
      <Section title="Upcoming shifts">
        {workerShifts.map((shift) => (
          <Card key={shift.id}>
            <View style={styles.rowBetween}>
              <View>
                <Text style={styles.cardTitle}>{shift.date}</Text>
                <Text style={styles.cardSubtle}>{shift.start} – {shift.end} • {shift.role}</Text>
                <Text style={styles.cardSubtle}>{shift.zone}</Text>
              </View>
              <StatusPill label={shift.status.replace('_', ' ')} tone="neutral" />
            </View>
          </Card>
        ))}
      </Section>

      <Section title="Availability & leave">
        <Card>
          <ListItem icon="calendar-clear-outline" title="Request leave" subtitle="Submit leave, RDO, or availability changes" />
          <Divider />
          <ListItem icon="repeat-outline" title="Swap request" subtitle="Request shift swap with qualified colleagues" />
        </Card>
      </Section>
    </View>
  );
}

function WorkerClock({ clockedIn, onBreak, onClockAction }: { clockedIn: boolean; onBreak: boolean; onClockAction: () => void }) {
  const actionLabel = !clockedIn ? 'Clock in' : !onBreak ? 'Start break' : 'Clock out';

  return (
    <View style={styles.stackGap}>
      <Card style={styles.centerCard}>
        <Ionicons name={clockedIn ? 'time' : 'time-outline'} size={38} color="#111827" />
        <Text style={styles.clockHeadline}>{clockedIn ? (onBreak ? 'Break in progress' : 'Shift in progress') : 'Not clocked in'}</Text>
        <Text style={styles.sectionText}>Location validated • Device synced • Exception-free session</Text>
        <PrimaryButton label={actionLabel} onPress={onClockAction} />
      </Card>

      <Section title="Clocking safeguards">
        <Card>
          <ListItem icon="location-outline" title="Geofencing active" subtitle="Clocking restricted to approved site perimeter" />
          <Divider />
          <ListItem icon="cloud-done-outline" title="Offline sync ready" subtitle="Events queue locally if signal drops" />
          <Divider />
          <ListItem icon="shield-checkmark-outline" title="Audit trail enabled" subtitle="Every attendance action is traceable" />
        </Card>
      </Section>
    </View>
  );
}

function WorkerPerformance() {
  return (
    <View style={styles.stackGap}>
      <Section title="Personal performance">
        <MetricsRow
          items={[
            { label: 'Productivity', value: '112%' },
            { label: 'Quality', value: '99.4%' },
            { label: 'Attendance', value: '100%' },
          ]}
        />
      </Section>

      <Section title="AI coaching insights">
        <Card>
          <ListItem icon="trending-up-outline" title="Strongest in wave picking" subtitle="You outperform your peer group by 9% in multi-line orders" />
          <Divider />
          <ListItem icon="construct-outline" title="Improvement opportunity" subtitle="Travel time in Zone C is 7% above best-practice benchmark" />
          <Divider />
          <ListItem icon="star-outline" title="Recommended development" subtitle="Cross-train in dispatch packing to increase shift flexibility and earnings potential" />
        </Card>
      </Section>
    </View>
  );
}

function SupervisorHome() {
  return (
    <View style={styles.stackGap}>
      <HeroCard
        title="Operations stable"
        subtitle="Dispatch 94% to plan • Picking 102% to plan • 3 active alerts"
        statLabel="Labour cost"
        statValue="$14.8k"
      />

      <Section title="Live KPIs">
        <MetricsRow
          items={[
            { label: 'Headcount', value: '46' },
            { label: 'Utilisation', value: '89%' },
            { label: 'OT risk', value: 'Low' },
          ]}
        />
      </Section>

      <Section title="AI recommendations">
        <Card>
          <ListItem icon="sparkles-outline" title="Reassign 2 operators to Dispatch" subtitle="Expected SLA recovery +6% with negligible cost impact" />
          <Divider />
          <ListItem icon="cash-outline" title="Reduce overtime in Zone B" subtitle="Swap one casual forklift driver to save 8.4% against plan" />
        </Card>
      </Section>
    </View>
  );
}

function SupervisorLive() {
  return (
    <View style={styles.stackGap}>
      <Section title="Active alerts">
        {liveAlerts.map((item) => (
          <Card key={item.id}>
            <View style={styles.rowBetween}>
              <View style={{ flex: 1, paddingRight: 12 }}>
                <Text style={styles.cardTitle}>{item.title}</Text>
                <Text style={styles.cardSubtle}>{item.detail}</Text>
              </View>
              <StatusPill label={item.severity} tone={item.severity === 'high' ? 'danger' : item.severity === 'medium' ? 'warning' : 'neutral'} />
            </View>
          </Card>
        ))}
      </Section>

      <Section title="Zone view">
        <Card>
          <ListItem icon="cube-outline" title="Picking" subtitle="18 active • 103% to plan • backlog stable" />
          <Divider />
          <ListItem icon="archive-outline" title="Packing" subtitle="12 active • 96% to plan • quality stable" />
          <Divider />
          <ListItem icon="bus-outline" title="Dispatch" subtitle="8 active • 88% to plan • SLA risk rising" />
        </Card>
      </Section>
    </View>
  );
}

function SupervisorTeam({ search, setSearch, filteredTeam }: { search: string; setSearch: (value: string) => void; filteredTeam: typeof teamData }) {
  return (
    <View style={styles.stackGap}>
      <Section title="Team management">
        <TextInput
          value={search}
          onChangeText={setSearch}
          placeholder="Search by worker or role"
          placeholderTextColor="#9CA3AF"
          style={styles.input}
        />
        {filteredTeam.map((member) => (
          <Card key={member.name}>
            <View style={styles.rowBetween}>
              <View>
                <Text style={styles.cardTitle}>{member.name}</Text>
                <Text style={styles.cardSubtle}>{member.role} • Productivity {member.productivity}%</Text>
              </View>
              <StatusPill label={member.status} tone={member.status === 'Idle' ? 'warning' : 'neutral'} />
            </View>
          </Card>
        ))}
      </Section>
    </View>
  );
}

function SupervisorApprovals() {
  return (
    <View style={styles.stackGap}>
      <Section title="Pending approvals">
        <Card>
          <ListItem icon="calendar-outline" title="Leave request" subtitle="Maria Chen • 24 Apr • Annual leave" />
          <Divider />
          <ListItem icon="swap-horizontal-outline" title="Shift swap" subtitle="James Ali ↔ Ben Kumar • Forklift ↔ Picker cross-cover" />
          <Divider />
          <ListItem icon="document-text-outline" title="Exception review" subtitle="Late clock-in flagged with valid gate entry evidence" />
        </Card>
      </Section>

      <Section title="Approver actions">
        <MetricsRow
          items={[
            { label: 'Pending', value: '7' },
            { label: 'High risk', value: '2' },
            { label: 'Auto-approved', value: '19' },
          ]}
        />
      </Section>
    </View>
  );
}

function ProfileCard({ role }: { role: Role }) {
  return (
    <View style={styles.stackGap}>
      <Section title="Profile & settings">
        <Card>
          <ListItem icon="person-circle-outline" title={role === 'worker' ? 'Alex Parker' : 'Samir Patel'} subtitle={role === 'worker' ? 'Warehouse Operator' : 'Operations Supervisor'} />
          <Divider />
          <ListItem icon="business-outline" title="Site" subtitle="Truganina Distribution Centre" />
          <Divider />
          <ListItem icon="shield-outline" title="Permissions" subtitle={role === 'worker' ? 'Clocking, shifts, performance' : 'Live ops, team, approvals'} />
        </Card>

        <Section title="App roadmap">
          <Card>
            <ListItem icon="scan-outline" title="Scanner integration" subtitle="Zebra device workflows for scan-triggered task tracking" />
            <Divider />
            <ListItem icon="notifications-outline" title="Push alerts" subtitle="SLA risk, roster changes, leave decisions, certification expiry" />
            <Divider />
            <ListItem icon="wifi-outline" title="Enhanced offline mode" subtitle="Queued sync for low-connectivity warehouse zones" />
          </Card>
        </Section>
      </Section>
    </View>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

function HeroCard({ title, subtitle, statLabel, statValue }: { title: string; subtitle: string; statLabel: string; statValue: string }) {
  return (
    <View style={styles.heroCard}>
      <View style={{ flex: 1 }}>
        <Text style={styles.heroTitle}>{title}</Text>
        <Text style={styles.heroSub}>{subtitle}</Text>
      </View>
      <View style={styles.heroStat}>
        <Text style={styles.heroStatLabel}>{statLabel}</Text>
        <Text style={styles.heroStatValue}>{statValue}</Text>
      </View>
    </View>
  );
}

function Card({ children, style }: { children: React.ReactNode; style?: object }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

function ListItem({ icon, title, subtitle }: { icon: keyof typeof Ionicons.glyphMap; title: string; subtitle: string }) {
  return (
    <View style={styles.listItem}>
      <View style={styles.listIconWrap}>
        <Ionicons name={icon} size={18} color="#111827" />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.cardTitle}>{title}</Text>
        <Text style={styles.cardSubtle}>{subtitle}</Text>
      </View>
    </View>
  );
}

function MetricsRow({ items }: { items: Array<{ label: string; value: string }> }) {
  return (
    <View style={styles.metricsRow}>
      {items.map((item) => (
        <View key={item.label} style={styles.metricCard}>
          <Text style={styles.metricValue}>{item.value}</Text>
          <Text style={styles.metricLabel}>{item.label}</Text>
        </View>
      ))}
    </View>
  );
}

function StatusPill({ label, tone }: { label: string; tone: 'neutral' | 'warning' | 'danger' }) {
  return <Text style={[styles.statusPill, tone === 'warning' && styles.statusWarning, tone === 'danger' && styles.statusDanger]}>{label}</Text>;
}

function Divider() {
  return <View style={styles.divider} />;
}

function Label({ children }: { children: React.ReactNode }) {
  return <Text style={styles.label}>{children}</Text>;
}

function SegmentButton({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={[styles.segmentButton, selected && styles.segmentButtonActive]}>
      <Text style={[styles.segmentButtonText, selected && styles.segmentButtonTextActive]}>{label}</Text>
    </Pressable>
  );
}

function PrimaryButton({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={styles.primaryButton}>
      <Text style={styles.primaryButtonText}>{label}</Text>
    </Pressable>
  );
}

function BottomNav({
  items,
  activeKey,
  onChange,
}: {
  items: Array<{ key: string; label: string; icon: keyof typeof Ionicons.glyphMap }>;
  activeKey: string;
  onChange: (key: string) => void;
}) {
  return (
    <View style={styles.bottomNav}>
      {items.map((item) => {
        const active = item.key === activeKey;
        return (
          <Pressable key={item.key} style={styles.navItem} onPress={() => onChange(item.key)}>
            <Ionicons name={item.icon} size={20} color={active ? '#111827' : '#6B7280'} />
            <Text style={[styles.navLabel, active && styles.navLabelActive]}>{item.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#F3F4F6',
  },
  appShell: {
    flex: 1,
  },
  authContainer: {
    flex: 1,
    justifyContent: 'center',
    padding: 20,
  },
  authCard: {
    backgroundColor: '#FFFFFF',
    borderRadius: 24,
    padding: 20,
    gap: 12,
    shadowColor: '#000',
    shadowOpacity: 0.06,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3,
  },
  brandRow: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'center',
  },
  brandIcon: {
    width: 48,
    height: 48,
    borderRadius: 16,
    backgroundColor: '#E5E7EB',
    alignItems: 'center',
    justifyContent: 'center',
  },
  eyebrow: {
    fontSize: 12,
    color: '#6B7280',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  authTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#111827',
  },
  header: {
    paddingHorizontal: 20,
    paddingTop: 16,
    paddingBottom: 12,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerTitle: {
    fontSize: 24,
    fontWeight: '700',
    color: '#111827',
  },
  headerSubtitle: {
    marginTop: 4,
    color: '#6B7280',
    fontSize: 13,
  },
  roleChip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: '#E5E7EB',
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  roleChipText: {
    textTransform: 'capitalize',
    color: '#111827',
    fontWeight: '600',
  },
  content: {
    paddingHorizontal: 20,
    paddingBottom: 120,
    gap: 18,
  },
  stackGap: {
    gap: 18,
  },
  section: {
    gap: 10,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
  },
  sectionText: {
    color: '#6B7280',
    fontSize: 14,
    lineHeight: 20,
  },
  heroCard: {
    backgroundColor: '#111827',
    borderRadius: 24,
    padding: 18,
    flexDirection: 'row',
    gap: 16,
    alignItems: 'center',
  },
  heroTitle: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '700',
  },
  heroSub: {
    marginTop: 6,
    color: '#D1D5DB',
    fontSize: 14,
    lineHeight: 20,
  },
  heroStat: {
    minWidth: 88,
    backgroundColor: '#1F2937',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  heroStatLabel: {
    color: '#9CA3AF',
    fontSize: 12,
  },
  heroStatValue: {
    color: '#FFFFFF',
    fontSize: 22,
    fontWeight: '700',
    marginTop: 4,
  },
  card: {
    backgroundColor: '#FFFFFF',
    borderRadius: 20,
    padding: 16,
    gap: 10,
    shadowColor: '#000',
    shadowOpacity: 0.04,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 2,
  },
  centerCard: {
    alignItems: 'center',
    gap: 14,
  },
  clockHeadline: {
    fontSize: 22,
    fontWeight: '700',
    color: '#111827',
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: '#111827',
  },
  cardSubtle: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 18,
    color: '#6B7280',
  },
  rowBetween: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  listItem: {
    flexDirection: 'row',
    gap: 12,
    alignItems: 'flex-start',
  },
  listIconWrap: {
    width: 34,
    height: 34,
    borderRadius: 12,
    backgroundColor: '#F3F4F6',
    alignItems: 'center',
    justifyContent: 'center',
  },
  metricsRow: {
    flexDirection: 'row',
    gap: 10,
  },
  metricCard: {
    flex: 1,
    backgroundColor: '#FFFFFF',
    borderRadius: 18,
    padding: 14,
    shadowColor: '#000',
    shadowOpacity: 0.03,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 5 },
    elevation: 2,
  },
  metricValue: {
    fontSize: 20,
    fontWeight: '700',
    color: '#111827',
  },
  metricLabel: {
    marginTop: 4,
    fontSize: 12,
    color: '#6B7280',
  },
  statusPill: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: '#E5E7EB',
    color: '#374151',
    overflow: 'hidden',
    textTransform: 'capitalize',
    fontSize: 12,
    fontWeight: '600',
  },
  statusWarning: {
    backgroundColor: '#FEF3C7',
    color: '#92400E',
  },
  statusDanger: {
    backgroundColor: '#FEE2E2',
    color: '#991B1B',
  },
  divider: {
    height: 1,
    backgroundColor: '#E5E7EB',
  },
  label: {
    color: '#374151',
    fontSize: 13,
    fontWeight: '600',
  },
  input: {
    backgroundColor: '#F9FAFB',
    borderColor: '#E5E7EB',
    borderWidth: 1,
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
    color: '#111827',
  },
  preferenceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginVertical: 4,
  },
  preferenceLabel: {
    color: '#374151',
    fontSize: 14,
  },
  segmentRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 6,
    marginBottom: 4,
  },
  segmentButton: {
    flex: 1,
    borderRadius: 16,
    paddingVertical: 10,
    alignItems: 'center',
    backgroundColor: '#F3F4F6',
  },
  segmentButtonActive: {
    backgroundColor: '#111827',
  },
  segmentButtonText: {
    color: '#374151',
    fontWeight: '600',
  },
  segmentButtonTextActive: {
    color: '#FFFFFF',
  },
  primaryButton: {
    backgroundColor: '#111827',
    borderRadius: 18,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 6,
  },
  primaryButtonText: {
    color: '#FFFFFF',
    fontWeight: '700',
    fontSize: 15,
  },
  bottomNav: {
    position: 'absolute',
    left: 16,
    right: 16,
    bottom: 16,
    backgroundColor: '#FFFFFF',
    borderRadius: 24,
    paddingVertical: 12,
    paddingHorizontal: 10,
    flexDirection: 'row',
    justifyContent: 'space-between',
    shadowColor: '#000',
    shadowOpacity: 0.08,
    shadowRadius: 18,
    shadowOffset: { width: 0, height: 10 },
    elevation: 8,
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    gap: 4,
  },
  navLabel: {
    fontSize: 11,
    color: '#6B7280',
    fontWeight: '600',
  },
  navLabelActive: {
    color: '#111827',
  },
});

export default App;
