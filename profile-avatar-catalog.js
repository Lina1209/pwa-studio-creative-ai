(function (root) {
  "use strict";
  // Shared local-only catalogue metadata. Profile selection remains distinct from Character Library records.
  const items = [
    { id: "portrait-violet", name: "Лавандовый портрет", category: "people", group: "Люди", representation: "2d", assetPath: "assets/avatars/2d/portrait-violet.svg" },
    { id: "forest-elf", name: "Лесная фея", category: "fantasy", group: "Фэнтези", representation: "2d", assetPath: "assets/avatars/2d/forest-elf.svg" },
    { id: "fox-scout", name: "Лисёнок", category: "animals", group: "Животные", representation: "2d", assetPath: "assets/avatars/2d/fox-scout.svg" },
    { id: "robo-buddy", name: "Робот-друг", category: "robots", group: "Роботы", representation: "2d", assetPath: "assets/avatars/2d/robo-buddy.svg" },
    { id: "katty-assistant", name: "Катти · помощница PWA Studio", category: "cartoon", group: "Мультяшные", representation: "2d", assetPath: "assets/avatars/2d/katty-assistant.svg", identityKey: "katty-katarina", identityManifest: "assets/characters/katty/identity.v1.json" },
    { id: "comic-star", name: "Комикс-герой", category: "cartoon", group: "Мультяшные", representation: "2d", assetPath: "assets/avatars/2d/comic-star.svg" },
    { id: "cosmo-pilot", name: "Космический пилот", category: "space", group: "Космос", representation: "2d", assetPath: "assets/avatars/2d/cosmo-pilot.svg" },
    { id: "sun-garden", name: "Солнечный сад", category: "nature", group: "Природа", representation: "2d", assetPath: "assets/avatars/2d/sun-garden.svg" },
    { id: "prism-orbit", name: "Призма", category: "abstract", group: "Абстракция", representation: "2d", assetPath: "assets/avatars/2d/prism-orbit.svg" }
  ].map(item => Object.freeze(item));
  const byId = id => items.find(item => item.id === id) || null;
  root.PWAProfileAvatarCatalog = Object.freeze({ version: 1, items: Object.freeze(items), getById: byId, getAssetPath: id => (byId(id) || items[0]).assetPath });
})(globalThis);
