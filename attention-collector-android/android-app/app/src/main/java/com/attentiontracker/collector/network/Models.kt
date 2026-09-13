package com.attentiontracker.collector.network

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass


@JsonClass(generateAdapter = true)
data class SimulateDayRequest(
    val archetype: String,
    @Json(name = "user_id") val userId: String = "demo_user"
)

@JsonClass(generateAdapter = true)
data class AppFeatureSummary(
    @Json(name = "package_name") val packageName: String,

    // Volume (M3)
    @Json(name = "session_count") val sessionCount: Int,
    @Json(name = "total_time_sec") val totalTimeSec: Double,
    @Json(name = "avg_session_duration_sec") val avgSessionDurationSec: Double,
    @Json(name = "max_session_duration_sec") val maxSessionDurationSec: Double,

    // Compulsiveness (M3)
    @Json(name = "interarrival_mean_sec") val interarrivalMeanSec: Double?,
    @Json(name = "sessions_under_30s_ratio") val sessionsUnder30sRatio: Double,
    @Json(name = "interarrival_under_2min_ratio") val interarrivalUnder2minRatio: Double?,

    // Temporal (M3)
    @Json(name = "late_night_usage_pct") val lateNightUsagePct: Double,
    @Json(name = "hourly_usage_entropy") val hourlyUsageEntropy: Double,
    @Json(name = "weekend_usage_ratio") val weekendUsageRatio: Double,

    // Transitions (M3)
    @Json(name = "productive_interruption_rate") val productiveInterruptionRate: Double,

    // Heuristic score (M4 — added when M4 was completed)
    @Json(name = "heuristic_score") val heuristicScore: Double
)

@JsonClass(generateAdapter = true)
data class CompletenessSummary(
    @Json(name = "is_complete") val isComplete: Boolean,
    @Json(name = "max_gap_hours") val maxGapHours: Double,
    val reason: String
)

@JsonClass(generateAdapter = true)
data class SimulateDayResponse(
    val archetype: String,
    @Json(name = "user_id") val userId: String,
    @Json(name = "raw_event_count") val rawEventCount: Int,
    @Json(name = "duplicate_count") val duplicateCount: Int,
    @Json(name = "session_count_total") val sessionCountTotal: Int,
    @Json(name = "outliers_capped") val outliersCapped: Int,
    val completeness: CompletenessSummary,
    @Json(name = "per_app_features") val perAppFeatures: List<AppFeatureSummary>,
    @Json(name = "scoring_status") val scoringStatus: String,
    @Json(name = "scoring_message") val scoringMessage: String
)