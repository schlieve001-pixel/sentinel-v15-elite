# County Map

All 64 Colorado counties configured in VeriFuse V2. Data sourced from `verifuse_v2/config/counties.yaml`.

---

## Summary

| Category | Count |
|----------|-------|
| Total counties configured | 64 |
| Enabled (automated scraping) | ~49 |
| Disabled (GovEase, pending) | ~2 |
| Manual (CORA request pipeline) | ~15 |

| Platform | Count |
|----------|-------|
| county_page | ~28 |
| manual | ~15 |
| realforeclose | 5 |
| gts | 6 |
| govease | 2 |

---

## Phase 1: Original 10 Counties (Enabled)

Large population centers with the highest foreclosure volume.

| County | Code | Platform | URL | Tier | Enabled |
|--------|------|----------|-----|------|---------|
| Denver | `denver` | county_page | [Public Trustee](https://www.denvergov.org/Government/Departments/Department-of-Finance/Public-Trustee) | large | Yes |
| Adams | `adams` | gts | [Public Trustee](https://adcogov.org/public-trustee) | large | Yes |
| Arapahoe | `arapahoe` | gts | [Public Trustee](https://www.arapahoegov.com/201/Public-Trustee) | large | Yes |
| Jefferson | `jefferson` | county_page | [Public Trustee](https://www.jeffco.us/732/Public-Trustee) | large | Yes |
| El Paso | `el_paso` | realforeclose | [Public Trustee](https://publictrustee.elpasoco.com/) | large | Yes |
| Douglas | `douglas` | gts | [Public Trustee](https://www.douglas.co.us/public-trustee/) | large | Yes |
| Boulder | `boulder` | gts | [Public Trustee](https://www.bouldercounty.org/departments/public-trustee/) | large | Yes |
| Larimer | `larimer` | realforeclose | [Public Trustee](https://www.larimer.org/public-trustee) | large | Yes |
| Weld | `weld` | gts | [Public Trustee](https://www.weldgov.com/Departments/Public-Trustee) | large | Yes |
| Mesa | `mesa` | realforeclose | [Public Trustee](https://www.mesacounty.us/public-trustee) | medium | Yes |

## Phase 1 Expansion: 5 Additional Counties

| County | Code | Platform | URL | Tier | Enabled |
|--------|------|----------|-----|------|---------|
| Pueblo | `pueblo` | county_page | [Public Trustee](https://county.pueblo.org/public-trustee) | medium | Yes |
| Summit | `summit` | realforeclose | [Public Trustee](https://www.summitcountyco.gov/201/Public-Trustee) | small | Yes |
| Teller | `teller` | govease | [Public Trustee](https://www.co.teller.co.us/PublicTrustee/) | small | **No** |
| Eagle | `eagle` | realforeclose | [Public Trustee](https://www.eaglecounty.us/Clerk/Public_Trustee/) | small | Yes |

## Phase 2: 8 New Counties

| County | Code | Platform | URL | Tier | Enabled |
|--------|------|----------|-----|------|---------|
| Garfield | `garfield` | gts | [Public Trustee](https://www.garfield-county.com/public-trustee/) | medium | Yes |
| Pitkin | `pitkin` | county_page | [Public Trustee](https://www.pitkincounty.com/175/Public-Trustee) | small | Yes |
| Routt | `routt` | county_page | [Public Trustee](https://co.routt.co.us/260/Public-Trustee) | small | Yes |
| Grand | `grand` | county_page | [Public Trustee](https://co.grand.co.us/192/Public-Trustee) | small | Yes |
| Broomfield | `broomfield` | county_page | [Public Trustee](https://www.broomfield.org/157/Public-Trustee) | medium | Yes |
| Clear Creek | `clear_creek` | county_page | [Public Trustee](https://www.clearcreekcounty.us/149/Public-Trustee) | rural | Yes |
| Gilpin | `gilpin` | county_page | [Public Trustee](https://www.co.gilpin.co.us/departments/public-trustee) | rural | Yes |

## Phase 3: 10+ Medium Counties

| County | Code | Platform | URL | Tier | Enabled |
|--------|------|----------|-----|------|---------|
| Morgan | `morgan` | county_page | [Public Trustee](https://www.co.morgan.co.us/public-trustee) | small | Yes |
| Fremont | `fremont` | county_page | [Public Trustee](https://www.fremontco.com/public-trustee) | medium | Yes |
| Park | `park` | county_page | [Public Trustee](https://www.parkco.us/236/Public-Trustee) | small | Yes |
| Lake | `lake` | county_page | [Public Trustee](https://www.lakecountyco.com/publictrustee) | rural | Yes |
| La Plata | `la_plata` | county_page | [Public Trustee](https://co.laplata.co.us/departments/public_trustee/) | medium | Yes |
| Montrose | `montrose` | county_page | [Public Trustee](https://www.montrosecounty.us/364/Public-Trustee) | medium | Yes |
| Delta | `delta` | county_page | [Public Trustee](https://www.deltacounty.com/363/Public-Trustee) | small | Yes |
| Elbert | `elbert` | county_page | [Public Trustee](https://www.elbertcounty-co.gov/277/Public-Trustee) | small | Yes |
| Logan | `logan` | county_page | [Public Trustee](https://www.logancountyco.gov/public-trustee) | small | Yes |
| Chaffee | `chaffee` | county_page | [Public Trustee](https://www.chaffeecounty.org/public-trustee) | small | Yes |

## Phase 4: Rural Counties

Many of these have 0-5 foreclosures per year. Counties with no web presence use the `manual` platform (CORA request pipeline).

### County Page (Automated)

| County | Code | URL | Tier | Enabled |
|--------|------|-----|------|---------|
| Alamosa | `alamosa` | [Public Trustee](https://www.alamosacounty.org/public-trustee) | rural | Yes |
| Archuleta | `archuleta` | [Public Trustee](https://www.archuletacounty.org/213/Public-Trustee) | rural | Yes |
| Gunnison | `gunnison` | [Public Trustee](https://www.gunnisoncounty.org/241/Public-Trustee) | small | Yes |
| Las Animas | `las_animas` | [Public Trustee](https://www.lasanimascounty.org/public-trustee) | small | Yes |
| Moffat | `moffat` | [Public Trustee](https://moffatcounty.net/public-trustee) | small | Yes |
| Montezuma | `montezuma` | [Public Trustee](https://www.montezumacounty.org/public-trustee.html) | small | Yes |
| Otero | `otero` | [Public Trustee](https://www.oterogov.com/public-trustee) | small | Yes |
| Ouray | `ouray` | [Public Trustee](https://www.ouraycountyco.gov/200/Public-Trustee) | rural | Yes |
| Rio Blanco | `rio_blanco` | [Public Trustee](https://www.rbc.us/197/Public-Trustee) | rural | Yes |

### GovEase (Disabled)

| County | Code | Tier | Enabled |
|--------|------|------|---------|
| San Miguel | `san_miguel` | rural | **No** |

### Manual (CORA Request Pipeline)

| County | Code | Tier |
|--------|------|------|
| Baca | `baca` | rural |
| Bent | `bent` | rural |
| Cheyenne | `cheyenne` | rural |
| Conejos | `conejos` | rural |
| Costilla | `costilla` | rural |
| Crowley | `crowley` | rural |
| Custer | `custer` | rural |
| Dolores | `dolores` | rural |
| Hinsdale | `hinsdale` | rural |
| Huerfano | `huerfano` | rural |
| Jackson | `jackson` | rural |
| Kiowa | `kiowa` | rural |
| Kit Carson | `kit_carson` | rural |
| Lincoln | `lincoln` | rural |
| Mineral | `mineral` | rural |
| Phillips | `phillips` | rural |
| Prowers | `prowers` | rural |
| Rio Grande | `rio_grande` | rural |
| Saguache | `saguache` | rural |
| San Juan | `san_juan` | rural |
| Sedgwick | `sedgwick` | rural |
| Washington | `washington` | rural |
| Yuma | `yuma` | rural |

---

## Counties NOT Yet Configured

The following Colorado counties are not yet in `counties.yaml` and would need to be added to reach the full 64:

- Review the current YAML configuration and compare against the official list of 64 Colorado counties to identify any gaps. Missing counties can be added following the [Adding a County](adding-a-county.md) guide.

---

## Platform Distribution

```
county_page   ████████████████████████████  ~28 counties
manual        ███████████████              ~15 counties
gts           ██████                        6 counties
realforeclose █████                         5 counties
govease       ██                            2 counties
```

## Tier Distribution

```
rural    ██████████████████████████████████  ~32 counties
small    ████████████████                    ~16 counties
medium   ████████████                        ~8 counties
large    █████████                            9 counties
```
