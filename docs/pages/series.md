---
layout: default
title: "시리즈"
permalink: /series/
---

## 시리즈별 포스트 모음

### 🏗️ 프로젝트
{% assign proj = site.posts | where: "category", "프로젝트" | sort: "date" | reverse %}
{% for post in proj %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }}) — *{{ post.excerpt }}*
{% endfor %}

### 🤖 에이전트
{% assign agents = site.posts | where: "category", "에이전트" | sort: "date" | reverse %}
{% for post in agents %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }})
{% endfor %}

### 🔧 기술
{% assign tech = site.posts | where: "category", "기술" | sort: "date" | reverse %}
{% for post in tech %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }})
{% endfor %}

### 💡 인사이트
{% assign insight = site.posts | where: "category", "인사이트" | sort: "date" | reverse %}
{% for post in insight %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }})
{% endfor %}

### 📌 시작
{% assign start = site.posts | where: "category", "시작" | sort: "date" | reverse %}
{% for post in start %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }})
{% endfor %}

### 🔐 특허
{% assign patent = site.posts | where: "category", "특허" | sort: "date" | reverse %}
{% for post in patent %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }})
{% endfor %}

### 🎨 예술
{% assign art = site.posts | where: "category", "예술" | sort: "date" | reverse %}
{% for post in art %}
- [{{ post.date | date: "%Y.%m.%d" }}] [{{ post.title }}]({{ post.url | prepend: site.baseurl }})
{% endfor %}
