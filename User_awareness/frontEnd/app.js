// Configuration
const API_BASE_URL = "http://localhost:8095"; 
const REFRESH_INTERVAL = 5000;
const ALERT_TIMEOUT = 30; // Seconds an alert stays active on the dashboard

// DOM Elements
const houseGrid = document.getElementById('house-grid');
const themeToggleButton = document.getElementById('theme-toggle');
const refreshTimerDiv = document.getElementById('refresh-timer');
let motionAlerts = {}; // Store alerts with timestamps for dynamic clearing

/**
 * Fetches the latest data from the Operator Control API.
 */
async function fetchData() {
    try {
        const [housesResponse, alertsResponse] = await Promise.all([
            fetch(`${API_BASE_URL}/houses`),
            fetch(`${API_BASE_URL}/motion_alerts`)
        ]);
        if (!housesResponse.ok || !alertsResponse.ok) {
            throw new Error(`API request failed`);
        }
        const housesData = await housesResponse.json();
        const alertsData = await alertsResponse.json();
        
        (alertsData.activeAlerts || []).forEach(key => {
            motionAlerts[key] = Date.now();
        });

        return { houses: housesData };
    } catch (error) {
        console.error("Failed to fetch data:", error);
        houseGrid.innerHTML = `<div class="col-12"><div class="alert alert-danger"><strong>Connection Error:</strong> Could not connect to the backend service.</div></div>`;
        return null;
    }
}

/**
 * Renders the entire dashboard.
 */
function renderDashboard(data) {
    if (!data) return;
    
    const activeAlertKeys = getActiveAlerts();
    renderGlobalAlert(activeAlertKeys);

    houseGrid.innerHTML = ''; 

    if (Object.keys(data.houses).length === 0) {
        houseGrid.innerHTML = `<p class="text-muted">No houses found or available.</p>`;
        return;
    }

    for (const houseId in data.houses) {
        const house = data.houses[houseId];
        if (house) {
            const houseCard = createHouseCard(house, activeAlertKeys);
            houseGrid.appendChild(houseCard);
        }
    }
}

/**
 * Gets a list of alert keys that are not stale and removes old ones.
 */
function getActiveAlerts() {
    const now = Date.now();
    const activeKeys = [];
    for (const key in motionAlerts) {
        if ((now - motionAlerts[key]) / 1000 < ALERT_TIMEOUT) {
            activeKeys.push(key);
        } else {
            delete motionAlerts[key];
        }
    }
    return activeKeys;
}

/**
 * Renders the global "THIEF DETECTED!" alert.
 */
function renderGlobalAlert(activeAlertKeys) {
    const alertContainer = document.getElementById('global-alert-container');

    if (activeAlertKeys.length > 0) {
        const alertDetails = activeAlertKeys.map(alertKey => {
            const [houseID, floorID, unitID] = alertKey.split('-');
            return `House ${houseID}, F${floorID}, U${unitID}`;
        }).join('; ');

        alertContainer.innerHTML = `
            <div class="alert alert-danger d-flex align-items-center shadow-lg" role="alert">
                <i class="bi bi-exclamation-triangle-fill fs-2 me-3"></i>
                <div>
                    <h4 class="alert-heading">THIEF DETECTED!</h4>
                    <p class="mb-0">
                        Active motion alert in: <strong>${alertDetails}</strong>.
                    </p>
                </div>
            </div>`;
    } else {
        alertContainer.innerHTML = '';
    }
}

/**
 * Creates an HTML card element for a single house.
 */
function createHouseCard(house, activeAlertKeys) {
    const isBreached = house.floors.some(floor => 
        floor.units.some(unit => activeAlertKeys.includes(`${house.houseID}-${floor.floorID}-${unit.unitID}`))
    );

    const card = document.createElement('div');
    card.className = 'col';
    
    let cardBodyHtml = '';
    
    (house.floors || []).forEach(floor => {
        (floor.units || []).forEach(unit => {
            cardBodyHtml += `<h6 class="mt-3 text-muted">F${floor.floorID}/U${unit.unitID}</h6>`;
            
            if (unit.devicesList && unit.devicesList.length > 0) {
                cardBodyHtml += '<ul class="list-group list-group-flush">';
                unit.devicesList.forEach(device => {
                    const icon = getDeviceIcon(device.deviceName, device.deviceStatus);
                    const statusClass = (device.deviceStatus || 'unknown').toLowerCase().replace(' ', '-');
                    const badgeColor = getStatusBadgeColor(device.deviceStatus);
                    
                    const unitKey = `${house.houseID}-${floor.floorID}-${unit.unitID}`;
                    const isAlerting = activeAlertKeys.includes(unitKey) && device.deviceName.includes('motion');
                    const alertClass = isAlerting ? 'list-group-item-danger' : '';

                    let descriptionHtml = `<small class="text-muted d-block">Last Update: ${new Date(device.lastUpdate).toLocaleTimeString()}</small>`;
                    
                    if (device.deviceName.includes('light_sensor') && typeof device.value === 'number') {
                        descriptionHtml += `<small class="text-muted d-block">Light Level: <strong>${device.value.toFixed(2)} lux</strong></small>`;
                    }

                    // FIX: This correctly displays the reason for the light's status, for both ON and OFF states.
                    if (device.deviceName.includes('light_switch') && device.lastCommandReason) {
                        const reasonColor = device.deviceStatus === 'ON' ? 'text-info' : 'text-secondary';
                        descriptionHtml += `<small class="${reasonColor} d-block">Reason: <strong>${device.lastCommandReason}</strong></small>`;
                    }

                    cardBodyHtml += `
                        <li class="list-group-item d-flex justify-content-between align-items-center ${alertClass}">
                            <div>
                                <i class="bi ${icon} me-2"></i>
                                <strong>${device.deviceName.replace(/_/g, ' ')}</strong>
                                ${descriptionHtml}
                            </div>
                            <span class="badge ${badgeColor} status-badge ${statusClass}">${device.deviceStatus}</span>
                        </li>`;
                });
                cardBodyHtml += '</ul>';
            } else {
                cardBodyHtml += '<p class="text-muted small">No devices in this unit.</p>';
            }
        });
    });

    const thingspeakLink = getThingSpeakLink(house.houseID);

    card.innerHTML = `
        <div class="card h-100 shadow-sm">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h5 class="mb-0">
                    <i class="bi bi-house-door-fill me-2"></i>${house.houseName}
                </h5>
                <span class="badge rounded-pill ${isBreached ? 'bg-danger security-status breach' : 'bg-success security-status'}">
                    <i class="bi ${isBreached ? 'bi-exclamation-shield-fill' : 'bi-shield-check'} me-1"></i>
                    ${isBreached ? 'BREACH' : 'SECURE'}
                </span>
            </div>
            <div class="card-body">${cardBodyHtml}</div>
            <div class="card-footer bg-transparent border-top-0">
                <a href="${thingspeakLink}" class="btn btn-outline-primary btn-sm w-100" target="_blank">
                    <i class="bi bi-graph-up-arrow me-2"></i>View ThingSpeak Chart
                </a>
            </div>
        </div>`;
    return card;
}

function getDeviceIcon(d,s){if(d.includes('light_sensor'))return'bi-brightness-high-fill';if(d.includes('light_switch'))return s==='ON'?'bi-lightbulb-fill':'bi-lightbulb-off';if(d.includes('motion_sensor'))return'bi-person-walking';return'bi-hdd'}
function getStatusBadgeColor(s){switch(s){case'ON':return'bg-success';case'OFF':return'bg-secondary';case'Detected':return'bg-warning text-dark';case'No Motion':return'bg-info text-dark';case'DISABLE':return'bg-dark';default:return'bg-light text-dark'}}
function getThingSpeakLink(h){const c={'1':'2884625','2':'2884626'};const i=c[h];return i?`https://thingspeak.com/channels/${i}`:'#'}

// --- Theme Toggler ---
themeToggleButton.addEventListener('click',()=>{const c=document.documentElement.getAttribute('data-bs-theme');const n=c==='dark'?'light':'dark';document.documentElement.setAttribute('data-bs-theme',n);themeToggleButton.innerHTML=n==='dark'?'<i class="bi bi-sun-fill"></i>':'<i class="bi bi-moon-stars-fill"></i>'});

// --- Main Application Logic ---
async function main(){const data=await fetchData();renderDashboard(data)}main();setInterval(main,REFRESH_INTERVAL);let countdown=REFRESH_INTERVAL/1000;setInterval(()=>{countdown=countdown>1?countdown-1:REFRESH_INTERVAL/1000;refreshTimerDiv.innerHTML=`<span class="spinner-border spinner-border-sm"></span> Refreshing in ${countdown}s`},1000);