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
    @Json(name = "session_count") val sessionCount: Int,
    @Json(name = "total_time_sec") val totalTimeSec: Double,
    @Json(name = "avg_session_duration_sec") val avgSessionDurationSec: Double,
    @Json(name = "max_session_duration_sec") val maxSessionDurationSec: Double,
    @Json(name = "interarrival_mean_sec") val interarrivalMeanSec: Double?,
    @Json(name = "sessions_under_30s_ratio") val sessionsUnder30sRatio: Double
)

@JsonClass(generateAdapter = true)
data class SimulateDayResponse(
    val archetype: String,
    @Json(name = "user_id") val userId: String,
    @Json(name = "raw_event_count") val rawEventCount: Int,
    @Json(name = "duplicate_count") val duplicateCount: Int,
    @Json(name = "session_count_total") val sessionCountTotal: Int,
    @Json(name = "outliers_capped") val outliersCapped: Int,
    @Json(name = "per_app_features") val perAppFeatures: List<AppFeatureSummary>,
    @Json(name = "scoring_status") val scoringStatus: String,
    @Json(name = "scoring_message") val scoringMessage: String
)