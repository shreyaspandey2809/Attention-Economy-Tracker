package com.attentiontracker.collector.data

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.attentiontracker.collector.network.BackendClient
import com.attentiontracker.collector.network.SimulateDayRequest
import com.attentiontracker.collector.network.SimulateDayResponse
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed class UiState {
    object Idle : UiState()
    object LoadingArchetypes : UiState()
    data class ArchetypesReady(val archetypes: List<String>, val selected: String) : UiState()
    object Simulating : UiState()
    data class Result(
        val archetypes: List<String>,
        val selected: String,
        val response: SimulateDayResponse
    ) : UiState()
    data class Error(val message: String, val archetypes: List<String>, val selected: String?) : UiState()
}

val ARCHETYPE_DESCRIPTIONS = mapOf(
    "BALANCED" to "Even mix of productive and entertainment apps, no strong compulsive signal.",
    "DOOMSCROLLER" to "Long sessions on addictive/entertainment apps, heavy late-night usage.",
    "BINGE_WEEKEND" to "Usage concentrated on weekends, long uninterrupted sessions.",
    "DEEP_WORKER" to "Long, infrequent sessions dominated by productive apps.",
    "COMPULSIVE_CHECKER" to "Very high session count, each session short — frequent re-opening rather than long sessions."
)

class SimulationViewModel : ViewModel() {

    private val _uiState = MutableStateFlow<UiState>(UiState.Idle)
    val uiState: StateFlow<UiState> = _uiState.asStateFlow()

    init {
        loadArchetypes()
    }

    fun loadArchetypes() {
        _uiState.value = UiState.LoadingArchetypes
        viewModelScope.launch {
            try {
                val archetypes = BackendClient.api.listArchetypes()
                val default = archetypes.firstOrNull() ?: ""
                _uiState.value = UiState.ArchetypesReady(archetypes, default)
            } catch (e: Exception) {
                _uiState.value = UiState.Error(
                    message = "Couldn't reach the backend at startup. " +
                        "Is it running, and is BACKEND_BASE_URL correct? (${e.message})",
                    archetypes = emptyList(),
                    selected = null
                )
            }
        }
    }

    fun selectArchetype(archetype: String) {
        val current = _uiState.value
        val archetypes = when (current) {
            is UiState.ArchetypesReady -> current.archetypes
            is UiState.Result -> current.archetypes
            is UiState.Error -> current.archetypes
            else -> emptyList()
        }
        _uiState.value = UiState.ArchetypesReady(archetypes, archetype)
    }

    fun simulateDay() {
        val current = _uiState.value
        val (archetypes, selected) = when (current) {
            is UiState.ArchetypesReady -> current.archetypes to current.selected
            is UiState.Result -> current.archetypes to current.selected
            else -> return
        }

        _uiState.value = UiState.Simulating
        viewModelScope.launch {
            try {
                val response = BackendClient.api.simulateDay(
                    SimulateDayRequest(archetype = selected)
                )
                _uiState.value = UiState.Result(archetypes, selected, response)
            } catch (e: Exception) {
                _uiState.value = UiState.Error(
                    message = "Simulation failed: ${e.message}",
                    archetypes = archetypes,
                    selected = selected
                )
            }
        }
    }
}
