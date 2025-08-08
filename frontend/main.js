const API_BASE_URL = "https://pi-promise.onrender.com"; // Change to your backend

document.addEventListener("DOMContentLoaded", () => {
    fetchUserProfile();
    fetchLeaderboard();

    document.getElementById("mine-btn").addEventListener("click", startMining);
    document.getElementById("watch-ad-btn").addEventListener("click", watchAd);
});

function fetchUserProfile() {
    fetch(`${API_BASE_URL}/api/user`)
        .then(res => res.json())
        .then(data => {
            document.getElementById("user-name").textContent = data.name;
            document.getElementById("user-rank").textContent = `Rank: ${data.rank}`;
            document.getElementById("user-coins").textContent = `Coins: ${data.coins}`;
            if (data.avatar) {
                document.getElementById("user-avatar").src = data.avatar;
            } else {
                document.getElementById("user-avatar").src = data.gender === "female" ? "avatar_female.png" : "avatar_male.png";
            }
        })
        .catch(err => console.error("Error fetching user profile:", err));
}

function fetchLeaderboard() {
    fetch(`${API_BASE_URL}/api/leaderboard`)
        .then(res => res.json())
        .then(data => {
            const lb = document.getElementById("leaderboard");
            lb.innerHTML = "";
            data.forEach(user => {
                const li = document.createElement("li");
                li.textContent = `${user.name} - ${user.coins} coins`;
                lb.appendChild(li);
            });
        })
        .catch(err => console.error("Error fetching leaderboard:", err));
}

function startMining() {
    fetch(`${API_BASE_URL}/api/mine`, { method: "POST" })
        .then(res => res.json())
        .then(data => {
            alert(data.message);
            fetchUserProfile();
        })
        .catch(err => console.error("Error starting mining:", err));
}

function watchAd() {
    fetch(`${API_BASE_URL}/api/watch-ad`, { method: "POST" })
        .then(res => res.json())
        .then(data => {
            alert(data.message);
            document.getElementById("ads-watched").textContent = `Ads Watched: ${data.adsWatched} / 5`;
            fetchUserProfile();
        })
        .catch(err => console.error("Error watching ad:", err));
}
