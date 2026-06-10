import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import {
  ActivityIndicator,
  SafeAreaView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { loadSession, logout } from "./src/api";
import BackupScreen from "./src/BackupScreen";
import GalleryScreen from "./src/GalleryScreen";
import LoginScreen from "./src/LoginScreen";
import { colors } from "./src/theme";

type View_ = "gallery" | "backup";

export default function App() {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [view, setView] = useState<View_>("gallery");

  useEffect(() => {
    loadSession().then((ok) => {
      setAuthed(ok);
      setReady(true);
    });
  }, []);

  if (!ready) {
    return (
      <View style={styles.loading}>
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  if (!authed) {
    return (
      <>
        <LoginScreen onSuccess={() => setAuthed(true)} />
        <StatusBar style="light" />
      </>
    );
  }

  return (
    <SafeAreaView style={styles.app}>
      <View style={styles.header}>
        <Text style={styles.brand}>PhotoNest</Text>
        <View style={styles.nav}>
          <TouchableOpacity onPress={() => setView("gallery")}>
            <Text style={view === "gallery" ? styles.activeTab : styles.tab}>Photos</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => setView("backup")}>
            <Text style={view === "backup" ? styles.activeTab : styles.tab}>Backup</Text>
          </TouchableOpacity>
          <TouchableOpacity
            onPress={async () => {
              await logout();
              setAuthed(false);
            }}
          >
            <Text style={styles.tab}>Sign out</Text>
          </TouchableOpacity>
        </View>
      </View>
      {view === "gallery" ? <GalleryScreen /> : <BackupScreen />}
      <StatusBar style="light" />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  app: { flex: 1, backgroundColor: colors.bg },
  loading: {
    flex: 1,
    backgroundColor: colors.bg,
    alignItems: "center",
    justifyContent: "center",
  },
  header: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomColor: colors.border,
    borderBottomWidth: 1,
  },
  brand: { color: colors.text, fontWeight: "600", fontSize: 16 },
  nav: { flexDirection: "row", gap: 18 },
  tab: { color: colors.muted },
  activeTab: { color: colors.accent, fontWeight: "600" },
});
