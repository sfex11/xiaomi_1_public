---
layout: default
title: "시리즈"
permalink: /series/
---

## 시리즈별 포스트 모음

### 🏗️ P001 Chatub — 에이전트 관제탑
{% assign chatub = site.posts | where: "category", "프로젝트" | sort: "date" %}
{% for post in chatub %}
{% if post.title contains "Chatub" or post.title contains "P001" or post.title contains "chatub" %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }} — *{{ post.excerpt }}*
{% endif %}
{% endfor %}

### 🤖 에이전트 연구
{% assign agents = site.posts | where: "category", "에이전트" | sort: "date" %}
{% for post in agents %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }}
{% endif %}
{% endfor %}

### 🔧 기술
{% assign tech = site.posts | where: "category", "기술" | sort: "date" %}
{% for post in tech %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }}
{% endif %}
{% endfor %}

### 💡 인사이트
{% assign insight = site.posts | where: "category", "인사이트" | sort: "date" %}
{% for post in insight %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }}
{% endif %}
{% endfor %}

### 📌 시작하기
{% assign start = site.posts | where: "category", "시작" | sort: "date" %}
{% for post in start %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }}
{% endif %}
{% endfor %}

### 🔐 특허
{% assign patent = site.posts | where: "category", "특허" | sort: "date" %}
{% for post in patent %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }}
{% endif %}
{% endfor %}

### 🎨 예술
{% assign art = site.posts | where: "category", "예술" | sort: "date" %}
{% for post in art %}
- [{{ post.date | date: "%Y.%m.%d" }}] {{ post.title }}
{% endif %}
{% endfor %}
