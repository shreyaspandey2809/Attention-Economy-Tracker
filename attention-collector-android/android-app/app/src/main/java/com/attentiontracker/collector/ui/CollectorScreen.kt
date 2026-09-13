package com.attentiontracker.collector.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import com.attentiontracker.collector.data.ARCHETYPE_DESCRIPTIONS
import com.attentiontracker.collector.data.SimulationViewModel
import com.attentiontracker.collector.data.UiState
import com.attentiontracker.collector.network.AppFeatureSummary
import com.attentiontracker.collector.ui.theme.*
import kotlin.math.roundToInt

private val KNOWN_APP_NAMES = mapOf(
    "com.instagram.android" to "Instagram",
    "com.zhiliaoapp.musically" to "TikTok",
    "com.twitter.android" to "X / Twitter",
    "com.google.android.gm" to "Gmail",
    "com.whatsapp" to "WhatsApp",
    "com.google.android.youtube" to "YouTube",
    "com.spotify.music" to "Spotify",
    "com.microsoft.office.word" to "Word",
    "com.google.android.apps.docs" to "Google Docs",
    "com.slack" to "Slack"
)

private fun shortAppName(pkg: String): String = KNOWN_APP_NAMES[pkg] ?: pkg

private fun formatSeconds(sec: Double?): String {
    if (sec == null) return "—"
    val totalSeconds = sec.roundToInt()
    val m = totalSeconds / 60
    val s = totalSeconds % 60
    return if (m == 0) "${s}s" else "${m}m ${s}s"
}

@Composable
fun CollectorScreen(viewModel: SimulationViewModel = viewModel()) {
    val state by viewModel.uiState.collectAsState()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BackgroundDark)
            .padding(20.dp)
    ) {
        HeaderSection()
        Spacer(Modifier.height(20.dp))

        when (val s = state) {
            is UiState.Idle, is UiState.LoadingArchetypes -> {
                Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = Amber)
                }
            }

            is UiState.ArchetypesReady -> {
                ControlPanel(
                    archetypes = s.archetypes,
                    selected = s.selected,
                    onSelect = viewModel::selectArchetype,
                    onSimulate = viewModel::simulateDay,
                    simulating = false
                )
                Spacer(Modifier.height(20.dp))
                EmptyResultsState()
            }

            is UiState.Simulating -> {
                ControlPanel(
                    archetypes = emptyList(),
                    selected = null,
                    onSelect = {},
                    onSimulate = {},
                    simulating = true
                )
                Spacer(Modifier.height(20.dp))
                Box(Modifier.fillMaxWidth().padding(top = 40.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = Amber)
                }
            }

            is UiState.Result -> {
                ControlPanel(
                    archetypes = s.archetypes,
                    selected = s.selected,
                    onSelect = viewModel::selectArchetype,
                    onSimulate = viewModel::simulateDay,
                    simulating = false
                )
                Spacer(Modifier.height(16.dp))
                PipelineStatsRow(s.response)
                Spacer(Modifier.height(20.dp))
                ResultsList(s.response.perAppFeatures)
                Spacer(Modifier.height(24.dp))
                InProgressScoringPanel(s.response.scoringMessage)
            }

            is UiState.Error -> {
                if (s.archetypes.isNotEmpty()) {
                    ControlPanel(
                        archetypes = s.archetypes,
                        selected = s.selected ?: s.archetypes.first(),
                        onSelect = viewModel::selectArchetype,
                        onSimulate = viewModel::simulateDay,
                        simulating = false
                    )
                    Spacer(Modifier.height(16.dp))
                }
                ErrorCard(s.message, onRetry = viewModel::loadArchetypes)
            }
        }
    }
}

@Composable
private fun HeaderSection() {
    Text(
        text = "ATTENTION ECONOMY TRACKER",
        color = TextFaint,
        fontSize = 12.sp,
        letterSpacing = 1.sp
    )
    Spacer(Modifier.height(6.dp))
    Text(
        text = "Simulate a day of usage",
        color = TextPrimary,
        fontSize = 24.sp,
        fontWeight = FontWeight.Medium
    )
    Spacer(Modifier.height(4.dp))
    Text(
        text = "This mock collector sends a simulated day of usage to the " +
            "backend, which runs the project's real pipeline — generation, " +
            "dedup, session building, outlier capping, and feature " +
            "extraction. Nothing shown below is fabricated.",
        color = TextDim,
        fontSize = 13.sp,
        lineHeight = 18.sp
    )
}

@Composable
private fun ControlPanel(
    archetypes: List<String>,
    selected: String?,
    onSelect: (String) -> Unit,
    onSimulate: () -> Unit,
    simulating: Boolean
) {
    var expanded by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(PanelDark, RoundedCornerShape(10.dp))
            .border(1.dp, BorderSoft, RoundedCornerShape(10.dp))
            .padding(16.dp)
    ) {
        Text("BEHAVIORAL ARCHETYPE", color = TextDim, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))

        Box {
            OutlinedButton(
                onClick = { if (archetypes.isNotEmpty()) expanded = true },
                modifier = Modifier.fillMaxWidth(),
                enabled = archetypes.isNotEmpty() && !simulating
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween,
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(selected?.replace("_", " ") ?: "Loading…", color = TextPrimary)
                    Icon(Icons.Default.ArrowDropDown, contentDescription = null, tint = TextDim)
                }
            }
            DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
                archetypes.forEach { archetype ->
                    DropdownMenuItem(
                        text = { Text(archetype.replace("_", " ")) },
                        onClick = {
                            onSelect(archetype)
                            expanded = false
                        }
                    )
                }
            }
        }

        selected?.let {
            Spacer(Modifier.height(8.dp))
            Text(
                text = ARCHETYPE_DESCRIPTIONS[it] ?: "",
                color = TextFaint,
                fontSize = 12.sp,
                lineHeight = 16.sp
            )
        }

        Spacer(Modifier.height(14.dp))

        Button(
            onClick = onSimulate,
            modifier = Modifier.fillMaxWidth(),
            enabled = !simulating && selected != null,
            colors = ButtonDefaults.buttonColors(containerColor = Amber, contentColor = BackgroundDark)
        ) {
            Text(if (simulating) "Simulating…" else "Simulate a day", fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun PipelineStatsRow(response: com.attentiontracker.collector.network.SimulateDayResponse) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(PanelDark, RoundedCornerShape(10.dp))
            .border(1.dp, BorderSoft, RoundedCornerShape(10.dp))
            .padding(14.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            StatItem("Events", response.rawEventCount.toString())
            StatItem("Duplicates", response.duplicateCount.toString())
            StatItem("Sessions", response.sessionCountTotal.toString())
            StatItem("Capped", response.outliersCapped.toString())
        }
        Spacer(Modifier.height(10.dp))
        HorizontalDivider(color = BorderSoft)
        Spacer(Modifier.height(10.dp))
        CompletenessIndicator(response.completeness)
    }
}

@Composable
private fun CompletenessIndicator(completeness: com.attentiontracker.collector.network.CompletenessSummary) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(
            modifier = Modifier
                .size(6.dp)
                .background(
                    if (completeness.isComplete) Sage else Amber,
                    CircleShape
                )
        )
        Spacer(Modifier.width(8.dp))
        Text(
            text = if (completeness.isComplete) "Day looks complete" else "Gap detected in usage data",
            color = TextDim,
            fontSize = 12.sp
        )
    }
    Spacer(Modifier.height(4.dp))
    Text(
        text = completeness.reason,
        color = TextFaint,
        fontSize = 11.sp,
        lineHeight = 15.sp
    )
}

@Composable
private fun StatItem(label: String, value: String) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(value, color = TextPrimary, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
        Text(label, color = TextFaint, fontSize = 11.sp)
    }
}

@Composable
private fun ResultsList(apps: List<AppFeatureSummary>) {
    Text("PER-APP USAGE TODAY", color = TextDim, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(10.dp))

    if (apps.isEmpty()) {
        EmptyResultsState(message = "No sessions were generated for this archetype today — try simulating again.")
        return
    }

    LazyColumn(
        modifier = Modifier.heightIn(max = 420.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)
    ) {
        items(apps) { app -> AppCard(app) }
    }
}

@Composable
private fun AppCard(app: AppFeatureSummary) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(PanelDark, RoundedCornerShape(10.dp))
            .border(1.dp, BorderSoft, RoundedCornerShape(10.dp))
            .padding(14.dp)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.Bottom
        ) {
            Column {
                Text(shortAppName(app.packageName), color = TextPrimary, fontSize = 16.sp, fontWeight = FontWeight.Medium)
                Text(formatSeconds(app.totalTimeSec), color = TextDim, fontSize = 12.sp)
            }
            HeuristicScoreBadge(app.heuristicScore)
        }
        Spacer(Modifier.height(8.dp))
        HorizontalDivider(color = BorderSoft)
        Spacer(Modifier.height(8.dp))
        FlowMetrics(app)
    }
}

@Composable
private fun HeuristicScoreBadge(score: Double) {
    // Score is 0-10 by construction (scoring/heuristic.py) — color
    // shifts from sage (low) through amber (mid) to a warmer tone
    // (high) so the number reads at a glance, not just numerically.
    val color = when {
        score < 3.0 -> Sage
        score < 6.0 -> Amber
        else -> ErrorRed
    }
    Column(horizontalAlignment = Alignment.End) {
        Text(
            text = String.format("%.1f", score),
            color = color,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold
        )
        Text("/ 10 heuristic", color = TextFaint, fontSize = 10.sp)
    }
}

@Composable
private fun FlowMetrics(app: AppFeatureSummary) {
    Column {
        MetricLine("Sessions", app.sessionCount.toString())
        MetricLine("Avg length", formatSeconds(app.avgSessionDurationSec))
        MetricLine("Longest", formatSeconds(app.maxSessionDurationSec))
        MetricLine("Avg gap between sessions", formatSeconds(app.interarrivalMeanSec))
        MetricLine("Short sessions (<30s)", "${(app.sessionsUnder30sRatio * 100).roundToInt()}%")
        MetricLine("Late-night usage", "${(app.lateNightUsagePct * 100).roundToInt()}%")
        MetricLine("Weekend share", "${(app.weekendUsageRatio * 100).roundToInt()}%")
        MetricLine("Time-of-day spread", "${(app.hourlyUsageEntropy * 100).roundToInt()}%")
        MetricLine("Interrupted productive app", "${(app.productiveInterruptionRate * 100).roundToInt()}%")
    }
}

@Composable
private fun MetricLine(label: String, value: String) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Text(label, color = TextDim, fontSize = 12.sp)
        Text(value, color = TextPrimary, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun EmptyResultsState(message: String = "Pick an archetype and tap \"Simulate a day\" to see computed usage features here.") {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .border(1.dp, BorderSoft, RoundedCornerShape(10.dp))
            .padding(32.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(message, color = TextFaint, fontSize = 13.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

@Composable
private fun InProgressScoringPanel(scoringMessage: String) {
    val rows = listOf(
        "LightGBM addiction / distraction" to "M5",
        "LSTM sequence score" to "M6",
        "Autoencoder anomaly signal" to "M6",
        "SHAP explanation" to "M7"
    )

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .border(1.dp, BorderSoft, RoundedCornerShape(10.dp))
            .padding(16.dp)
    ) {
        Text("MODEL-BASED SCORING — STILL IN PROGRESS", color = TextFaint, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(12.dp))

        rows.forEach { (label, tag) ->
            Row(
                modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Text(label, color = TextDim, fontSize = 13.sp, modifier = Modifier.weight(1f))
                Box(
                    modifier = Modifier
                        .border(1.dp, BorderSoft, RoundedCornerShape(4.dp))
                        .padding(horizontal = 8.dp, vertical = 2.dp)
                ) {
                    Text(tag, color = TextFaint, fontSize = 10.sp)
                }
            }
            HorizontalDivider(color = BorderSoft)
        }

        Spacer(Modifier.height(14.dp))
        Text(scoringMessage, color = TextFaint, fontSize = 12.sp, lineHeight = 17.sp)
    }
}

@Composable
private fun ErrorCard(message: String, onRetry: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(PanelDark, RoundedCornerShape(10.dp))
            .border(1.dp, ErrorRed, RoundedCornerShape(10.dp))
            .padding(16.dp)
    ) {
        Text(message, color = ErrorRed, fontSize = 13.sp, lineHeight = 18.sp)
        Spacer(Modifier.height(12.dp))
        OutlinedButton(onClick = onRetry) {
            Text("Retry")
        }
    }
}